# ProcureFlow — Aplikasi Procurement

Aplikasi Flask untuk alur Purchase Request, approval, pengadaan/dispatch stok,
Purchase Order, penerimaan gudang, dan laporan.

## Menjalankan aplikasi

Gunakan Python 3.10 atau lebih baru:

```powershell
cd procurement_app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Buka `http://127.0.0.1:5000`. Aplikasi wajib menggunakan SQLite. File database
`procurement.db` dibuat otomatis di folder `procurement_app/` saat aplikasi
dijalankan pertama kali; tabel dan akun demo juga diinisialisasi otomatis.
Semua request, approval, supplier, PO, notifikasi, penerimaan, dan stok disimpan
di file tersebut dan tetap ada setelah aplikasi dihentikan.
Untuk lingkungan selain demo, set `PROCUREMENT_SECRET_KEY` ke nilai acak yang
rahasia dan `PROCUREMENT_ADMIN_PASSWORD` ke password admin yang kuat sebelum
menjalankan aplikasi. `DATABASE_URL` tidak digunakan karena spesifikasi
mewajibkan SQLite. Gunakan `FLASK_DEBUG=1` hanya saat pengembangan lokal.

Untuk membuat salinan cadangan, hentikan aplikasi lalu salin
`procurement.db` ke lokasi aman. Jangan hapus database jika ingin menyimpan data.

## Akun demo

| Peran | Username | Password awal |
| --- | --- | --- |
| Admin | `admin` | `admin123` |
| Requester | `requester1` | `pass` |
| Procurement | `procurement1` | `pass` |
| Approver | `approver1` | `pass` |
| Warehouse | `warehouse1` | `pass` |

Ganti password akun demo sebelum aplikasi digunakan di lingkungan bersama.
Admin dapat membuat dan mengubah akun/peran melalui menu **Pengguna**.

## Ringkasan alur

1. Requester membuat Purchase Request dan dapat mengunggah dokumen pendukung.
2. Approver menyetujui atau mengembalikan request dengan catatan.
3. Procurement memeriksa stok: dispatch langsung jika stok cukup, atau membuat
   dan mengirim PO ke supplier.
4. Warehouse mencatat pemeriksaan barang. Penerimaan sesuai PO menambah stok
   dan menyelesaikan request; PO berstatus diterima hingga procurement menutupnya.
   Ketidaksesuaian dicatat sebagai komplain dan PO tetap terkirim untuk tindak lanjut.
5. Requester menerima notifikasi dalam aplikasi ketika request disetujui,
   dikembalikan, dipenuhi dari stok, PO dikirim, atau barang diterima/bermasalah.
6. Laporan merangkum status request, PO per supplier/periode, dan penerimaan.

OCR bersifat opsional. Instal dependensi dengan
`python -m pip install -r requirements-ocr.txt`, serta aplikasi Tesseract OCR
pada sistem. Gambar PNG/JPG diproses dengan OCR. PDF hingga 10 halaman dibaca
langsung jika mengandung teks, dan dirender lalu diproses dengan OCR jika
berupa hasil scan. OCR mengenali label sederhana seperti `Nama Barang:`,
`Qty:`, `Spesifikasi:`, dan `Anggaran:`; hasil ekstraksi harus diperiksa
sebelum request dikirim.
