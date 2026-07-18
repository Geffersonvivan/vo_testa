// Inicializa os campos de data com Flatpickr (calendário que abre ao clicar).
// Os campos enviam o valor real em Y-m-d (para o Django) e exibem d/m/Y ao usuário.
(function () {
    function init() {
        if (typeof flatpickr === 'undefined') return;

        // Localiza para português, se o pacote de idioma carregou.
        if (flatpickr.l10ns && flatpickr.l10ns.pt) {
            flatpickr.localize(flatpickr.l10ns.pt);
        }

        var checkinEl = document.querySelector('[data-picker="checkin"]');
        var checkoutEl = document.querySelector('[data-picker="checkout"]');
        if (!checkinEl) return;

        var base = {
            dateFormat: 'Y-m-d',   // valor enviado no form
            altInput: true,        // campo visível separado
            altFormat: 'd/m/Y',    // formato exibido
            minDate: 'today',      // bloqueia datas passadas
            disableMobile: false,  // usa o picker nativo no celular
        };

        var fpCheckout = checkoutEl ? flatpickr(checkoutEl, base) : null;

        flatpickr(checkinEl, Object.assign({}, base, {
            onChange: function (selecionadas) {
                if (!fpCheckout || !selecionadas[0]) return;
                // Check-out tem de ser ao menos 1 dia depois do check-in.
                var proxima = new Date(selecionadas[0].getTime());
                proxima.setDate(proxima.getDate() + 1);
                fpCheckout.set('minDate', proxima);
                var atual = fpCheckout.selectedDates[0];
                if (atual && atual <= selecionadas[0]) {
                    fpCheckout.setDate(proxima, true);
                }
            }
        }));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
