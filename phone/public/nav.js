(function () {
  var framed = false;
  try { framed = window.self !== window.top; } catch (e) { framed = true; }
  if (framed || new URLSearchParams(location.search).has('bare')) return;

  var path = location.pathname.replace(/\/+$/, '') || '/';
  var here = path === '/' || path === '/start' ? 'home' : path.slice(1);
  var links = [
    ['home', '/', 'Home'],
    ['phone', '/phone', 'Phone'],
    ['stage', '/stage', 'Stage rail'],
    ['install', '/start#install', 'Install'],
    ['github', 'https://github.com/Skilux/domovoy', 'GitHub']
  ];

  var style = document.createElement('style');
  style.textContent =
    '.dnav{position:fixed;z-index:1000;top:0;left:0;right:0;height:52px;box-sizing:border-box;display:flex;align-items:center;gap:22px;padding:0 20px;' +
    'background:rgba(10,13,24,.92);border-bottom:1px solid rgba(255,255,255,.2);color:#fff;transition:opacity .4s ease;' +
    'font:600 17px/1 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}' +
    '.dnav a{color:#fff;text-decoration:none;white-space:nowrap;padding:8px 0;border-bottom:2px solid transparent}' +
    '.dnav a:hover{border-bottom-color:rgba(255,255,255,.5)}' +
    '.dnav a.on{border-bottom-color:#a7c957;color:#d6ec9c}' +
    '.dnav .dnav-brand{display:flex;align-items:center;gap:10px;margin-right:auto;padding:0;border:0;font-weight:800;letter-spacing:.16em}' +
    '.dnav .dnav-brand:hover{border:0}' +
    '.dnav-brand img{width:32px;height:32px;display:block;image-rendering:pixelated}' +
    '.dnav-links{display:flex;align-items:center;gap:22px;overflow-x:auto;scrollbar-width:none}' +
    '.dnav-links::-webkit-scrollbar{display:none}' +
    'body:has(.page.open) .dnav{opacity:.12}' +
    '@media (max-width:640px){.dnav{gap:12px;padding:0 12px;font-size:15px}.dnav-links{gap:14px}.dnav-brand span{display:none}}';
  document.head.appendChild(style);

  var nav = document.createElement('nav');
  nav.className = 'dnav';
  nav.setAttribute('aria-label', 'DOMOVOY pages');
  var brand = document.createElement('a');
  brand.className = 'dnav-brand';
  brand.href = '/';
  brand.innerHTML = '<img src="/domovoy.svg" alt="" width="32" height="32"><span>DOMOVOY</span>';
  var list = document.createElement('div');
  list.className = 'dnav-links';
  links.forEach(function (l) {
    var a = document.createElement('a');
    a.href = l[1];
    a.textContent = l[2];
    if (l[0] === here) { a.className = 'on'; a.setAttribute('aria-current', 'page'); }
    list.appendChild(a);
  });
  nav.appendChild(brand);
  nav.appendChild(list);
  document.documentElement.classList.add('has-nav');
  document.body.insertBefore(nav, document.body.firstChild);
})();
