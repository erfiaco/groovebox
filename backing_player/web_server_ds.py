// ── File list ─────────────────────────────────────────────────────────────
let currentScrollTop = 0;

function renderList(sel) {
  let html = '<div class="fl-dir-label">' + escapeHtml(sel.dir) + '</div>';
  sel.items.forEach(function(item, i) {
    const active = i === sel.idx ? ' sel' : '';
    var cls = '', label = item.name;
    if (item.kind === 'wav') {
      cls   = 'fl-wav';
      label = item.name.replace(/_/g,' ').replace(/\.wav$/i,'');
    } else if (item.kind === 'dir') {
      cls = 'fl-dir-item';
    } else if (item.kind === 'up') {
      cls = 'fl-up';
    }
    html += '<div class="fl-item ' + cls + active + '" data-index="' + i + '">' + escapeHtml(label) + '</div>';
  });
  
  // Guardar posición actual del scroll antes de reemplazar el contenido
  const wasVisible = fileListEl.classList.contains('visible');
  const savedScrollTop = fileListEl.scrollTop;
  
  fileListEl.innerHTML = html;
  fileListEl.className = 'visible';
  
  // Restaurar la posición del scroll si la lista ya estaba visible
  if (wasVisible && savedScrollTop > 0) {
    fileListEl.scrollTop = savedScrollTop;
  }
  
  const selEl = fileListEl.querySelector('.sel');
  if (selEl && !wasVisible) {
    // Solo hacer scroll automático la primera vez que se muestra la lista
    const cRect = fileListEl.getBoundingClientRect();
    const iRect = selEl.getBoundingClientRect();
    if (iRect.bottom > cRect.bottom)
      fileListEl.scrollTop += iRect.bottom - cRect.bottom;
    else if (iRect.top < cRect.top)
      fileListEl.scrollTop -= cRect.top - iRect.top;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/[&<>]/g, function(m) {
    if (m === '&') return '&amp;';
    if (m === '<') return '&lt;';
    if (m === '>') return '&gt;';
    return m;
  });
}

// Manejar clics en los items de la lista
fileListEl.addEventListener('click', function(e) {
  let target = e.target;
  while (target && target !== fileListEl && !target.classList.contains('fl-item')) {
    target = target.parentElement;
  }
  if (target && target.classList.contains('fl-item')) {
    const index = target.getAttribute('data-index');
    if (index !== null) {
      // Enviar selección al servidor
      fetch('/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index: parseInt(index) })
      }).catch(console.error);
    }
  }
});

// Guardar posición del scroll cuando el usuario hace scroll manualmente
fileListEl.addEventListener('scroll', function() {
  if (fileListEl.classList.contains('visible')) {
    currentScrollTop = fileListEl.scrollTop;
  }
});
