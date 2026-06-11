import os
import sys
import threading
import time
import pytest
import uvicorn
from playwright.sync_api import sync_playwright

# Path setups
from pathlib import Path
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import server

PORT = 8529

def run_server():
    uvicorn.run(server.app, host="127.0.0.1", port=PORT, log_level="warning")

@pytest.fixture(scope="module", autouse=True)
def dev_server():
    os.environ["MAPS_SERVER_KEY"] = "test-key"
    os.environ["MAPS_BROWSER_KEY"] = "test-key"
    
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(1.5)  # Wait for server to spin up
    yield

def test_project_console_crud():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        # Load the presentation dashboard
        page.goto(f"http://127.0.0.1:{PORT}/presentation")
        page.wait_for_selector("#projectSelect")
        
        # 1. Assert default options exist
        options = page.eval_on_selector_all("#projectSelect option", "nodes => nodes.map(n => n.innerText)")
        assert len(options) >= 2
        assert "Lawn Advisor Presentation" in options
        assert "Forenly AI Platform" in options
        
        # 2. Test "New Project" creation
        prompts = ["Test Project Auto", "https://test.forenly.ai"]
        def handle_dialog(dialog):
            if dialog.type == "prompt":
                val = prompts.pop(0)
                dialog.accept(val)
            else:
                dialog.accept() # For confirmation popups
                
        page.on("dialog", handle_dialog)
        
        # Click the New button
        page.click("button[title='New Project']")
        page.wait_for_timeout(200)
        
        # Assert option was added and is selected
        options = page.eval_on_selector_all("#projectSelect option", "nodes => nodes.map(n => n.innerText)")
        assert "Test Project Auto" in options
        
        selected_val = page.eval_on_selector("#projectSelect", "node => node.value")
        assert selected_val.startswith("proj_")
        
        target_url = page.input_value("#targetPageUrl")
        assert target_url == "https://test.forenly.ai"
        
        # 3. Test "Rename Project"
        prompts = ["Renamed Auto Project"]
        page.click("button[title='Rename Project']")
        page.wait_for_timeout(200)
        
        options = page.eval_on_selector_all("#projectSelect option", "nodes => nodes.map(n => n.innerText)")
        assert "Renamed Auto Project" in options
        assert "Test Project Auto" not in options
        
        # 4. Test "Delete Project"
        page.click("button[title='Delete Project']")
        page.wait_for_timeout(200)
        
        options = page.eval_on_selector_all("#projectSelect option", "nodes => nodes.map(n => n.innerText)")
        assert "Renamed Auto Project" not in options
        
        browser.close()
