// Forenly AVIP — core utilities (DOM shorthand, theme, escaping, markdown)
const $ = id => document.getElementById(id);

function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
  const newTheme = (currentTheme === 'dark') ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', newTheme);
  localStorage.setItem('theme', newTheme);
}

function esc(unsafe) {
  return unsafe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function parseMarkdownSimple(md) {
  let html = md;
  html = html.replace(/### (.*?)\n/g, '<h3>$1</h3>');
  html = html.replace(/## (.*?)\n/g, '<h2>$1</h2>');
  html = html.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
  html = html.replace(/^- (.*?)\n/gm, '<li>$1</li>');
  html = html.replace(/(\s*<li>.*?<\/li>)/gs, '<ul>$1</ul>');
  html = html.replace(/<\/ul>\s*<ul>/g, '');
  html = html.replace(/\n/g, '<br>');
  return html;
}

