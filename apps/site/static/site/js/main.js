/* ========== Scroll Reveal ========== */
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('visible');
        }
    });
}, { threshold: 0.1 });

document.querySelectorAll('.fade-section').forEach(el => observer.observe(el));

/* ========== Menu Mobile ========== */
const menuBtn = document.getElementById('menuBtn');
const mobileMenu = document.getElementById('mobileMenu');
const menuOverlay = document.getElementById('menuOverlay');
const menuIcon = document.getElementById('menuIcon');
const closeIcon = document.getElementById('closeIcon');
let menuOpen = false;

function toggleMenu() {
    menuOpen = !menuOpen;
    mobileMenu.classList.toggle('open', menuOpen);
    menuOverlay.classList.toggle('open', menuOpen);
    menuIcon.classList.toggle('hidden', menuOpen);
    closeIcon.classList.toggle('hidden', !menuOpen);
    document.body.style.overflow = menuOpen ? 'hidden' : '';
}

if (menuBtn) {
    menuBtn.addEventListener('click', toggleMenu);
    menuOverlay.addEventListener('click', toggleMenu);

    document.querySelectorAll('.mobile-link').forEach(link => {
        link.addEventListener('click', () => {
            if (menuOpen) toggleMenu();
        });
    });
}

/* Âncoras do menu: topo do alvo alinhado à base do header (todas iguais) */
const headerEl = document.querySelector('header');
const ANCORAS_MENU = new Set([
    '#inicio',
    '#sobre',
    '#quartos',
    '#dia-pousada',
    '#eventos',
    '#experiencias',
    '#galeria',
    '#contato',
]);

function headerOffset() {
    return headerEl ? Math.ceil(headerEl.getBoundingClientRect().height) : 0;
}

function syncHeaderOffset() {
    document.documentElement.style.setProperty('--header-offset', `${headerOffset()}px`);
}
syncHeaderOffset();
window.addEventListener('resize', syncHeaderOffset);

function hashDeHref(href) {
    if (!href || !href.includes('#')) return '';
    return '#' + href.split('#')[1].split(/[?&]/)[0];
}

function revelarAncora(el) {
    el.querySelectorAll('.fade-section').forEach(s => s.classList.add('visible'));
    if (el.classList.contains('fade-section')) el.classList.add('visible');
}

function yAlvoAncora(el) {
    /* Mede depois do fade (sem translateY) para todas as seções caírem na mesma linha */
    return Math.round(el.getBoundingClientRect().top + window.scrollY - headerOffset());
}

function scrollNaDivisa(hash, { smooth = true } = {}) {
    if (!ANCORAS_MENU.has(hash)) return;
    if (hash === '#inicio') {
        window.scrollTo({ top: 0, behavior: smooth ? 'smooth' : 'auto' });
        return;
    }
    const el = document.querySelector(hash);
    if (!el) return;
    revelarAncora(el);
    syncHeaderOffset();
    void el.offsetHeight; /* reflow após tirar translateY do fade */
    const top = Math.max(0, yAlvoAncora(el));
    window.scrollTo({ top, behavior: smooth ? 'smooth' : 'auto' });

    const corrigir = () => {
        syncHeaderOffset();
        const ajuste = Math.max(0, yAlvoAncora(el));
        if (Math.abs(ajuste - window.scrollY) > 3) {
            window.scrollTo({ top: ajuste, behavior: 'auto' });
        }
    };
    if (smooth) {
        window.addEventListener('scrollend', corrigir, { once: true });
        setTimeout(corrigir, 450); /* fallback se não houver scrollend */
    } else {
        requestAnimationFrame(corrigir);
    }
}

function linkMesmaPagina(a, href) {
    if (href.startsWith('#')) return true;
    try {
        return new URL(a.href, location.origin).pathname === location.pathname;
    } catch (_) {
        return false;
    }
}

if (ANCORAS_MENU.has(location.hash)) {
    window.addEventListener('load', () => {
        syncHeaderOffset();
        scrollNaDivisa(location.hash, { smooth: false });
    });
}

document.querySelectorAll('a[href*="#"]').forEach(a => {
    a.addEventListener('click', (ev) => {
        const href = a.getAttribute('href') || '';
        const hash = hashDeHref(href);
        if (!ANCORAS_MENU.has(hash)) return;
        if (!linkMesmaPagina(a, href)) return;
        if (hash !== '#inicio' && !document.querySelector(hash)) return;
        ev.preventDefault();
        history.pushState(null, '', hash);
        syncHeaderOffset();
        scrollNaDivisa(hash);
    });
});

/* ========== Máscaras CPF / telefone (WhatsApp) ========== */
function soDigitos(v) {
    return String(v || '').replace(/\D/g, '');
}

function mascaraCpf(v) {
    const d = soDigitos(v).slice(0, 11);
    return d
        .replace(/(\d{3})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d{1,2})$/, '$1-$2');
}

function mascaraTelefone(v) {
    const d = soDigitos(v).slice(0, 11);
    if (d.length <= 10) {
        return d
            .replace(/(\d{2})(\d)/, '($1) $2')
            .replace(/(\d{4})(\d)/, '$1-$2');
    }
    return d
        .replace(/(\d{2})(\d)/, '($1) $2')
        .replace(/(\d{5})(\d)/, '$1-$2');
}

function aplicarMascara(el) {
    const tipo = el.getAttribute('data-mask');
    const fmt = tipo === 'cpf' ? mascaraCpf : tipo === 'telefone' ? mascaraTelefone : null;
    if (!fmt) return;
    const sync = () => {
        const pos = el.selectionStart;
        const antes = el.value.length;
        el.value = fmt(el.value);
        const depois = el.value.length;
        if (document.activeElement === el && typeof pos === 'number') {
            const nova = Math.max(0, pos + (depois - antes));
            try { el.setSelectionRange(nova, nova); } catch (_) { /* ignore */ }
        }
    };
    el.addEventListener('input', sync);
    el.addEventListener('blur', sync);
    if (el.value) sync();
}

document.querySelectorAll('[data-mask="cpf"], [data-mask="telefone"]').forEach(aplicarMascara);
