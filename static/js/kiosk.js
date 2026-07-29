$(document).ready(function() {
    let currentTrxId = "";
    let currentNrp = "";
    let simulatedKwh = 0.00;
    let chargingInterval = null;
    let pollingTimer = null;
    let countdownTimer = null; // Tambahan variabel untuk timer QRIS

    // Fungsi pindah layar
    function showStep(stepNumber) {
        $('.step-container').hide();
        $(`#step-${stepNumber}`).fadeIn();
    }

    showStep(0);

    // STEP 0 -> STEP 1 (Sentuh Layar)
    $('#step-0').click(function() {
        $('#input-nrp').val(''); // Kosongkan input
        showStep(1);
    });

    // Tombol Batal di Step 1
    $('#btn-cancel-nrp').click(function() {
        showStep(0);
    });

    // STEP 1 -> STEP 2 (Mulai Charging)
    $('#btn-start').click(function() {
        currentNrp = $('#input-nrp').val().trim();
        if (!currentNrp) {
            alert("Silakan masukkan NRP.");
            return;
        }

        let btn = $(this);
        btn.prop('disabled', true).html('<i class="fa-solid fa-spinner fa-spin"></i> Menghubungkan...');

        $.ajax({
            url: '/api/kiosk/start',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ nrp: currentNrp }),
            success: function(response) {
                currentTrxId = response.trx_id;
                simulatedKwh = 0.00;
                $('#live-kwh').text(simulatedKwh.toFixed(2));
                
                showStep(2);
                
                // Kembalikan tombol ke semula untuk transaksi berikutnya
                btn.prop('disabled', false).html('<i class="fa-solid fa-bolt"></i> Mulai Charging');
                
                // Simulasi kWh bertambah (Nanti data aslinya ditarik via AJAX dari PLC)
                chargingInterval = setInterval(function() {
                    simulatedKwh += 0.05; // Bertambah 0.05 kWh tiap detik
                    $('#live-kwh').text(simulatedKwh.toFixed(2));
                }, 1000);
            },
            error: function() {
                alert("Gagal terhubung ke mesin SPKLU.");
                btn.prop('disabled', false).html('<i class="fa-solid fa-bolt"></i> Mulai Charging');
            }
        });
    });

    // STEP 2 -> STEP 3 (Stop & Generate QR)
    $('#btn-stop').click(function() {
        clearInterval(chargingInterval);
        
        let btn = $(this);
        btn.prop('disabled', true).html('<i class="fa-solid fa-spinner fa-spin"></i> Menghentikan...');

        $.ajax({
            url: '/api/kiosk/stop',
            type: 'POST',
            contentType: 'application/json',
            // Kita kirim data kWh simulasi ke server untuk dihitung harganya
            data: JSON.stringify({ trx_id: currentTrxId, kwh_used: parseFloat(simulatedKwh.toFixed(2)) }),
            success: function(response) {
                $('#bill-kwh').text(response.kwh_amount);
                $('#bill-price').text("Rp " + response.price.toLocaleString('id-ID'));
                
                $('#qrcode-container').empty();
                new QRCode(document.getElementById("qrcode-container"), {
                    text: response.qris_string,
                    width: 250, height: 250
                });

                // Kembalikan tombol stop seperti semula
                btn.prop('disabled', false).html('<i class="fa-solid fa-stop"></i> Selesai & Bayar');

                showStep(3);
                
                // Mulai waktu mundur 5 menit (300 detik)
                startCountdown(300); 
                // Mulai cek status pembayaran ke database
                startPolling(response.trx_id);
            },
            error: function() {
                alert("Gagal menerbitkan QRIS.");
                btn.prop('disabled', false).html('<i class="fa-solid fa-stop"></i> Selesai & Bayar');
            }
        });
    });

    // FUNGSI WAKTU MUNDUR QRIS (5 MENIT)
    function startCountdown(duration) {
        let timer = duration, minutes, seconds;
        
        // Bersihkan timer lama jika ada
        if (countdownTimer) clearInterval(countdownTimer);

        countdownTimer = setInterval(function () {
            minutes = parseInt(timer / 60, 10);
            seconds = parseInt(timer % 60, 10);

            minutes = minutes < 10 ? "0" + minutes : minutes;
            seconds = seconds < 10 ? "0" + seconds : seconds;

            $('#timer').text(minutes + ":" + seconds);

            if (--timer < 0) {
                // WAKTU HABIS!
                clearInterval(countdownTimer);
                clearInterval(pollingTimer);
                showStep(5); // Pindah ke Layar Gagal / Timeout
                setTimeout(function() { location.reload(); }, 10000); // Kembali ke awal setelah 10 detik
            }
        }, 1000);
    }

    // FUNGSI POLLING CEK STATUS PEMBAYARAN KE SERVER
    function startPolling(trx_id) {
        // Bersihkan timer polling lama jika ada
        if (pollingTimer) clearInterval(pollingTimer);

        pollingTimer = setInterval(function() {
            $.get(`/api/kiosk/status/${trx_id}`, function(response) {
                if (response.status === "PAID") {
                    // PEMBAYARAN SUKSES!
                    clearInterval(pollingTimer);
                    clearInterval(countdownTimer);
                    showStep(4); // Pindah ke Layar Sukses, Unlock Kabel
                    setTimeout(function() { location.reload(); }, 10000); // Kembali ke awal setelah 10 detik
                }
            });
        }, 3000); // Cek tiap 3 detik
    }
});