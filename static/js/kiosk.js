/**
 * SPKLU / Charging Station Kiosk Application Controller
 * Tech Stack: jQuery, Bootstrap 5, FastAPI Backend (SQLAlchemy + BCA QRIS)
 */

$(document).ready(function () {
    // =========================================================================
    // STATE MANAGEMENT (VARIABEL GLOBAL KHUSUS KIOSK)
    // =========================================================================
    let currentTrxCode = "";
    let currentNrp = "";
    let currentFlowType = "POSTPAID"; // 'PREPAID' atau 'POSTPAID'
    let simulatedKwh = 0.00;

    // Timer Handlers
    let chargingInterval = null;
    let pollingTimer = null;
    let countdownTimer = null;

    // =========================================================================
    // NAVIGATION HELPER (PINDAH LAYAR CONTAINER)
    // =========================================================================
    /**
     * Memindahkan tampilan layar Kiosk berdasarkan Step ID
     * @param {string|number} stepId - Contoh: 0, 1, 'select-flow', 2, 3, 4, 5, 'recovery'
     */
    function showStep(stepId) {
        $('.step-container').addClass('d-none').hide();
        $(`#step-${stepId}`).removeClass('d-none').fadeIn(300);
    }

    // Inisialisasi awal: Layar Standby (Step 0)
    showStep(0);

    // =========================================================================
    // STEP 0 -> STEP 1: TOUCH TO START & INPUT NRP
    // =========================================================================
    $('#step-0').click(function () {
        $('#input-nrp').val('');
        $('#nrp-error-msg').addClass('d-none').text('');
        showStep(1);
    });

    $('#btn-cancel-nrp').click(function () {
        showStep(0);
    });

    // =========================================================================
    // STEP 1: VALIDASI NRP & CEK TUNGGAKAN (user_pending)
    // =========================================================================
    $('#btn-verify-nrp').click(function () {
        currentNrp = $('#input-nrp').val().trim();
        if (!currentNrp) {
            showNrpError("Silakan masukkan NRP Anda.");
            return;
        }

        let btn = $(this);
        btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin me-2"></i>Memeriksa NRP...');
        $('#nrp-error-msg').addClass('d-none');

        $.ajax({
            url: '/api/kiosk/verify-nrp',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ nrp: currentNrp }),
            success: function (response) {
                btn.prop('disabled', false).html('Lanjutkan <i class="fas fa-arrow-right ms-2"></i>');

                // SKENARIO A: Memiliki Tagihan Tertunggak di user_pending (Recovery Flow)
                if (response.status === "UNPAID_BILL_FOUND") {
                    currentTrxCode = response.unpaid_trx_code;
                    $('#unpaid-user-name').text(response.name);
                    
                    let unpaidAmount = parseFloat(response.amount) || 0;
                    $('#unpaid-amount').text("Rp " + unpaidAmount.toLocaleString('id-ID'));

                    showStep('recovery');
                    return;
                }

                // SKENARIO B: Bebas Tunggakan -> Pindah ke Layar Pilih Mode (Prepaid / Postpaid)
                $('#user-display-name').text(response.name);
                showStep('select-flow');
            },
            error: function (xhr) {
                btn.prop('disabled', false).html('Lanjutkan <i class="fas fa-arrow-right ms-2"></i>');
                let errDetail = xhr.responseJSON ? xhr.responseJSON.detail : "Gagal memverifikasi NRP.";
                showNrpError(errDetail);
            }
        });
    });

    function showNrpError(msg) {
        $('#nrp-error-msg').removeClass('d-none').text(msg);
    }

    // =========================================================================
    // STEP PILIH MODE: FLOW 1 (PRE-PAID) VS FLOW 2 (POST-PAID)
    // =========================================================================
    $('#btn-choose-prepaid').click(function () {
        currentFlowType = "PREPAID";
        $('#input-prepaid-amount').val('');
        showStep('input-prepaid');
    });

    $('#btn-choose-postpaid').click(function () {
        currentFlowType = "POSTPAID";
        startPostpaidCharging();
    });

    // =========================================================================
    // FLOW 1 (PRE-PAID): GENERATE QRIS TERLEBIH DAHULU
    // =========================================================================
    $('#btn-submit-prepaid').click(function () {
        let amount = parseFloat($('#input-prepaid-amount').val());
        if (!amount || amount < 5000) {
            alert("Nominal pengisian minimal Rp 5.000");
            return;
        }

        let btn = $(this);
        btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin me-2"></i>Menerbitkan QRIS...');

        $.ajax({
            url: '/api/kiosk/prepaid/create-qris',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ nrp: currentNrp, amount: amount }),
            success: function (response) {
                btn.prop('disabled', false).html('Bayar Sekarang');
                currentTrxCode = response.transaction_code;

                // Tampilkan Layar QRIS
                $('#bill-kwh').text("-");
                renderQRIS(response.qr_content, response.amount);
                showStep(3);

                startCountdown(300); // 5 Menit Expired
                startPolling(currentTrxCode, function () {
                    // Success Callback -> Setelah Prepaid Lunas, Baru Mulai Charging!
                    startPrepaidChargingSession();
                });
            },
            error: function () {
                btn.prop('disabled', false).html('Bayar Sekarang');
                alert("Gagal menerbitkan QRIS. Silakan coba lagi.");
            }
        });
    });

    // =========================================================================
    // FLOW 2 (POST-PAID): LANGSUNG CHARGING
    // =========================================================================
    function startPostpaidCharging() {
        $.ajax({
            url: '/api/kiosk/postpaid/start',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ nrp: currentNrp }),
            success: function (response) {
                currentTrxCode = response.transaction_code;
                simulatedKwh = 0.00;
                $('#live-kwh').text("0.00");

                showStep(2);
                startKwhSimulation();
            },
            error: function () {
                alert("Gagal terhubung dengan mesin PLC SPKLU.");
            }
        });
    }

    // SIMULASI METERAN KWH
    function startKwhSimulation() {
        if (chargingInterval) clearInterval(chargingInterval);
        chargingInterval = setInterval(function () {
            simulatedKwh += 0.05;
            $('#live-kwh').text(simulatedKwh.toFixed(2));
        }, 1000);
    }

    // STOP CHARGING ON FLOW 2 -> GENERATE BILL QRIS
    $('#btn-stop-charging').click(function () {
        clearInterval(chargingInterval);

        let btn = $(this);
        btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin me-2"></i>Menghentikan Daya...');

        $.ajax({
            url: '/api/kiosk/postpaid/stop',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                transaction_code: currentTrxCode,
                kwh_used: parseFloat(simulatedKwh.toFixed(2))
            }),
            success: function (response) {
                btn.prop('disabled', false).html('<i class="fas fa-stop-circle me-2"></i>Selesai & Bayar');

                $('#bill-kwh').text(response.kwh_used.toFixed(2) + " kWh");
                renderQRIS(response.qr_content, response.total_price);

                showStep(3);
                startCountdown(300);
                startPolling(currentTrxCode, function () {
                    // Success Callback -> Pembayaran Selesai
                    showStep(4);
                    resetToStandbyAfterDelay(10000);
                });
            },
            error: function () {
                btn.prop('disabled', false).html('<i class="fas fa-stop-circle me-2"></i>Selesai & Bayar');
                alert("Gagal memproses tagihan pengisian daya.");
            }
        });
    });

    // =========================================================================
    // RECOVERY FLOW: PELUNASAN TAGIHAN TERTUNGGAK
    // =========================================================================
    $('#btn-pay-unpaid').click(function () {
        let btn = $(this);
        btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin me-2"></i>Memuat QRIS...');

        $.ajax({
            url: `/api/kiosk/check-status/${currentTrxCode}`,
            type: 'GET',
            success: function (response) {
                btn.prop('disabled', false).html('Bayar Tagihan Sekarang');

                $('#bill-kwh').text((response.kwh_amount || 0) + " kWh");
                renderQRIS(response.qr_content || "", response.price || response.amount || 0);
                showStep(3);

                startCountdown(300);
                startPolling(currentTrxCode, function () {
                    alert("Tagihan tertunggak telah lunas! Akses NRP Anda dipulihkan.");
                    showStep(4);
                    resetToStandbyAfterDelay(5000);
                });
            }
        });
    });

    // =========================================================================
    // CORE FUNCTION 1: QR CODE RENDERER
    // =========================================================================
    function renderQRIS(qrString, priceAmount) {
        let formattedPrice = parseFloat(priceAmount) || 0;
        $('#bill-price').text("Rp " + formattedPrice.toLocaleString('id-ID'));
        $('#qrcode-container').empty();

        if (qrString) {
            new QRCode(document.getElementById("qrcode-container"), {
                text: qrString,
                width: 240,
                height: 240,
                colorDark: "#000000",
                colorLight: "#ffffff",
                correctLevel: QRCode.CorrectLevel.H
            });
        }
    }

    // =========================================================================
    // CORE FUNCTION 2: COUNTDOWN TIMER (5 MENIT EXPIRED)
    // =========================================================================
    function startCountdown(durationSeconds) {
        let timer = durationSeconds;
        let minutes = 0;
        let seconds = 0;

        if (countdownTimer) clearInterval(countdownTimer);

        countdownTimer = setInterval(function () {
            minutes = parseInt(timer / 60, 10);
            seconds = parseInt(timer % 60, 10);

            minutes = minutes < 10 ? "0" + minutes : minutes;
            seconds = seconds < 10 ? "0" + seconds : seconds;

            $('#timer-countdown').text(minutes + ":" + seconds);

            if (--timer < 0) {
                clearInterval(countdownTimer);
                if (pollingTimer) clearInterval(pollingTimer);

                showStep(5);
                resetToStandbyAfterDelay(10000);
            }
        }, 1000);
    }

    // =========================================================================
    // CORE FUNCTION 3: AJAX POLLING STATUS PEMBAYARAN (QRIS MPM INQUIRY)
    // =========================================================================
    function startPolling(transactionCode, onSuccessCallback) {
        if (pollingTimer) clearInterval(pollingTimer);

        console.log(`[AJAX Polling] Memulai polling QRIS MPM Inquiry untuk TRX: ${transactionCode}`);

        pollingTimer = setInterval(function () {
            $.ajax({
                url: `/api/kiosk/check-status/${transactionCode}`,
                type: 'GET',
                dataType: 'json',
                success: function (response) {
                    if (response.status === "PAID") {
                        clearInterval(pollingTimer);
                        if (countdownTimer) clearInterval(countdownTimer);

                        console.log("[AJAX Polling] Pembayaran Terkonfirmasi LUNAS!");
                        if (typeof onSuccessCallback === 'function') {
                            onSuccessCallback();
                        }
                    } else if (response.status === "EXPIRED" || response.status === "FAILED") {
                        clearInterval(pollingTimer);
                        if (countdownTimer) clearInterval(countdownTimer);

                        showStep(5);
                        resetToStandbyAfterDelay(10000);
                    }
                },
                error: function (err) {
                    console.error("[AJAX Polling Error]: Gagal mengecek status", err);
                }
            });
        }, 3000);
    }

    // =========================================================================
    // HELPER: UTILITAS AUTO-RESET TO STANDBY & RESET STATE
    // =========================================================================
    function resetToStandbyAfterDelay(delayMs) {
        setTimeout(function () {
            if (chargingInterval) clearInterval(chargingInterval);
            if (pollingTimer) clearInterval(pollingTimer);
            if (countdownTimer) clearInterval(countdownTimer);
            
            // Bersihkan State Variabel Global
            currentTrxCode = "";
            currentNrp = "";
            simulatedKwh = 0.00;

            showStep(0);
        }, delayMs);
    }

    function startPrepaidChargingSession() {
        showStep(2);
        startKwhSimulation();
        setTimeout(function () {
            clearInterval(chargingInterval);
            showStep(4);
            resetToStandbyAfterDelay(10000);
        }, 15000);
    }
});