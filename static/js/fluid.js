/* ============================================================
   Fluid — física de interface (Apple "Designing Fluid Interfaces")
   Springs interrompíveis, háptico e respeito a reduced-motion.
   Sem dependências. Usado por Reservas (corredor + timeline).
   ============================================================ */
(function (global) {
  "use strict";

  var mediaRM = global.matchMedia
    ? global.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false };

  function reducedMotion() { return mediaRM.matches; }

  // Um tique de háptico no mesmo frame do evento causal (§13). No-op onde não há suporte.
  function haptic(ms) {
    if (reducedMotion()) return;
    if (global.navigator && typeof global.navigator.vibrate === "function") {
      try { global.navigator.vibrate(ms || 8); } catch (e) {}
    }
  }

  // Converte os parâmetros de designer da Apple (response em s, bounce 0..1)
  // para rigidez/amortecimento de um oscilador de massa 1.
  //   response = tempo para assentar · bounce = 1 - razão de amortecimento
  function fromApple(response, bounce) {
    var omega = (2 * Math.PI) / Math.max(response, 0.01);
    var zeta = 1 - (bounce || 0);            // bounce 0 => crítico (sem overshoot)
    return { stiffness: omega * omega, damping: 2 * zeta * omega };
  }

  // Integra um spring de `from` a `to`, carregando a velocidade inicial (§4/§5).
  // Anima a partir do valor ATUAL (presentation value) — pronto para interrupção.
  // Retorna stop(); em reduced-motion salta direto para o destino.
  function spring(opts) {
    var to = opts.to;
    var onUpdate = opts.onUpdate || function () {};
    var onComplete = opts.onComplete || function () {};

    if (reducedMotion()) {
      onUpdate(to); onComplete(); return function () {};
    }

    var p = fromApple(opts.response != null ? opts.response : 0.35,
                      opts.bounce != null ? opts.bounce : 0);
    var k = p.stiffness, c = p.damping;
    var x = opts.from != null ? opts.from : 0;
    var v = opts.velocity || 0;
    var restD = opts.restDelta != null ? opts.restDelta : 0.25;
    var restV = opts.restSpeed != null ? opts.restSpeed : 0.25;
    var raf = 0, last = 0, alive = true;

    function frame(now) {
      if (!alive) return;
      if (!last) last = now;
      var dt = Math.min((now - last) / 1000, 1 / 30);   // trava passos longos (aba em 2º plano)
      last = now;
      // Semi-implícito: estável mesmo com springs rígidos.
      var a = -k * (x - to) - c * v;
      v += a * dt;
      x += v * dt;
      if (Math.abs(x - to) < restD && Math.abs(v) < restV) {
        onUpdate(to); alive = false; onComplete(); return;
      }
      onUpdate(x);
      raf = global.requestAnimationFrame(frame);
    }
    raf = global.requestAnimationFrame(frame);
    return function stop() { alive = false; global.cancelAnimationFrame(raf); };
  }

  // Dois springs X/Y independentes (§3 "decompose 2D motion").
  function spring2d(opts) {
    var curX = opts.fromX, curY = opts.fromY, done = 0;
    function emit() { opts.onUpdate(curX, curY); }
    function finished() { if (++done === 2 && opts.onComplete) opts.onComplete(); }
    var stopX = spring({
      from: opts.fromX, to: opts.toX, velocity: opts.velocityX,
      response: opts.response, bounce: opts.bounce,
      onUpdate: function (x) { curX = x; emit(); }, onComplete: finished
    });
    var stopY = spring({
      from: opts.fromY, to: opts.toY, velocity: opts.velocityY,
      response: opts.response, bounce: opts.bounce,
      onUpdate: function (y) { curY = y; emit(); }, onComplete: finished
    });
    return function () { stopX(); stopY(); };
  }

  // Resistência progressiva além de um limite (§9 rubber-band).
  function rubberband(overshoot, dimension, constant) {
    constant = constant || 0.55;
    return (overshoot * dimension * constant) /
           (dimension + constant * Math.abs(overshoot));
  }

  // Rastreia posição+tempo para estimar velocidade no release (§5).
  function velocityTracker() {
    var hist = [];
    return {
      push: function (x, y, t) {
        hist.push({ x: x, y: y, t: t });
        if (hist.length > 6) hist.shift();
      },
      velocity: function () {
        if (hist.length < 2) return { x: 0, y: 0 };
        var a = hist[0], b = hist[hist.length - 1];
        var dt = (b.t - a.t) / 1000;
        if (dt <= 0) return { x: 0, y: 0 };
        return { x: (b.x - a.x) / dt, y: (b.y - a.y) / dt };
      },
      reset: function () { hist.length = 0; }
    };
  }

  global.Fluid = {
    reducedMotion: reducedMotion,
    haptic: haptic,
    spring: spring,
    spring2d: spring2d,
    rubberband: rubberband,
    velocityTracker: velocityTracker,
    fromApple: fromApple
  };
})(window);
