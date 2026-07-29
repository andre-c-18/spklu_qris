$(document).ready(function() {
    
    // Fungsi untuk mengambil dan merender data transaksi
    function loadTransactions(startDate = '', endDate = '') {
        $('#table-body').html('<tr><td colspan="5" class="text-center"><div class="spinner-border text-primary" role="status"></div> Memuat data...</td></tr>');
        
        let queryParams = [];
        if (startDate) queryParams.push(`start_date=${startDate}`);
        if (endDate) queryParams.push(`end_date=${endDate}`);
        
        let url = '/admin/api/transactions';
        if (queryParams.length > 0) {
            url += '?' + queryParams.join('&');
        }

        $.ajax({
            url: url,
            type: 'GET',
            success: function(data) {
                let html = '';
                if (data.length === 0) {
                    html = '<tr><td colspan="5" class="text-center text-muted">Tidak ada data transaksi ditemukan.</td></tr>';
                } else {
                    data.forEach(function(row) {
                        // Format Tanggal (dari ISO string)
                        let dateObj = new Date(row.created_at);
                        let dateStr = dateObj.toLocaleString('id-ID');
                        
                        // Format Harga Rupiah
                        let priceStr = "Rp " + row.price.toLocaleString('id-ID');
                        
                        // Badge Status
                        let badgeClass = 'bg-secondary';
                        if(row.status === 'PAID') badgeClass = 'bg-success';
                        else if(row.status === 'PENDING') badgeClass = 'bg-warning text-dark';
                        else if(row.status === 'FAILED' || row.status === 'EXPIRED') badgeClass = 'bg-danger';

                        html += `
                            <tr>
                                <td>${dateStr}</td>
                                <td><small class="text-muted">${row.id}</small></td>
                                <td><span class="text-primary fw-bold">${row.nrp}</span></td>
                                <td><strong>${row.kwh_amount}</strong></td>
                                <td>${priceStr}</td>
                                <td><span class="badge ${badgeClass}">${row.status}</span></td>
                            </tr>
                        `;
                    });
                }
                $('#table-body').html(html);
            },
            error: function() {
                $('#table-body').html('<tr><td colspan="5" class="text-center text-danger">Gagal mengambil data dari server.</td></tr>');
            }
        });
    }

    // Load data pertama kali saat halaman dibuka
    loadTransactions();

    // FUNGSI CHART.JS
    let revenueChart = null;

    function loadChart() {
        $.ajax({
            url: '/admin/api/chart-data',
            type: 'GET',
            success: function(data) {
                const ctx = document.getElementById('revenueChart').getContext('2d');
                
                // Jika chart sudah ada, hancurkan dulu sebelum digambar ulang (mencegah bug tumpuk)
                if (revenueChart) {
                    revenueChart.destroy();
                }

                revenueChart = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: data.labels, // Tanggal
                        datasets: [{
                            label: 'Pendapatan (Rp)',
                            data: data.revenues, // Data Harga
                            backgroundColor: 'rgba(54, 162, 235, 0.6)',
                            borderColor: 'rgba(54, 162, 235, 1)',
                            borderWidth: 1,
                            yAxisID: 'y'
                        },
                        {
                            label: 'Daya Terjual (kWh)',
                            data: data.kwhs, // Data kWh
                            type: 'line', // Mix chart (bar & line)
                            backgroundColor: 'rgba(255, 193, 7, 1)',
                            borderColor: 'rgba(255, 193, 7, 1)',
                            borderWidth: 2,
                            tension: 0.3, // Membuat garis agak melengkung
                            yAxisID: 'y1'
                        }]
                    },
                    options: {
                        responsive: true,
                        interaction: {
                            mode: 'index',
                            intersect: false,
                        },
                        scales: {
                            y: {
                                type: 'linear',
                                display: true,
                                position: 'left',
                                title: { display: true, text: 'Rupiah (Rp)' }
                            },
                            y1: {
                                type: 'linear',
                                display: true,
                                position: 'right',
                                title: { display: true, text: 'Daya (kWh)' },
                                grid: { drawOnChartArea: false } // Agar garis grid tidak bertumpuk
                            }
                        }
                    }
                });
            },
            error: function() {
                console.error("Gagal memuat data chart");
            }
        });
    }

    // Load chart saat pertama kali halaman dibuka
    loadChart();

    // Event Submit Filter Form
    $('#filter-form').submit(function(e) {
        e.preventDefault(); // Mencegah reload halaman
        let start = $('#start-date').val();
        let end = $('#end-date').val();
        loadTransactions(start, end);
    });

    // Event Reset Filter
    $('#btn-reset').click(function() {
        $('#start-date').val('');
        $('#end-date').val('');
        loadTransactions();
    });

    // Event Download Excel
    $('#btn-download').click(function() {
        let start = $('#start-date').val();
        let end = $('#end-date').val();
        
        let url = '/admin/api/download-excel';
        let queryParams = [];
        if (start) queryParams.push(`start_date=${start}`);
        if (end) queryParams.push(`end_date=${end}`);
        
        if (queryParams.length > 0) {
            url += '?' + queryParams.join('&');
        }
        
        // Membuka URL ini akan otomatis men-trigger file download di browser
        window.location.href = url;
    });
});