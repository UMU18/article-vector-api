"""Seeder CLI - generates dummy articles with static templates.

Dispatches them through the exact same async pipeline as production data.

Usage::

    python -m app.cli seed --count 500 --batch-size 50
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from faker import Faker

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.domain.entities.article import Article


logger = get_logger(__name__)


_TOPICS = [
    "Teknologi",
    "Artificial Intelligence",
    "Ekonomi Digital",
    "Olahraga",
    "Kesehatan Mental",
    "Politik",
    "Budaya Nusantara",
    "Pendidikan",
    "Lingkungan Hidup",
    "Inovasi Startup",
]


# Template statis yang komprehensif (Judul dan Konten) untuk Vector Search.
CONTENT_TEMPLATES = {
    "Teknologi": {
        "titles": [
            "Tren Gadget dan Perangkat Keras Terbaru di Indonesia",
            "Mengapa Cloud Computing Semakin Penting untuk Perusahaan",
        ],
        "contents": [
            (
                "Perkembangan teknologi saat ini sangat pesat. Inovasi perangkat "
                "keras dan lunak terus memajukan berbagai industri, memudahkan "
                "aktivitas sehari-hari manusia dari komunikasi hingga otomatisasi "
                "pekerjaan rumit."
            ),
            (
                "Era transformasi digital menuntut perusahaan untuk terus "
                "beradaptasi. Adopsi cloud computing dan Internet of Things (IoT) "
                "telah menjadi standar baru dalam efisiensi operasional bisnis "
                "modern."
            ),
        ],
    },
    "Artificial Intelligence": {
        "titles": [
            "Masa Depan AI di Sektor Kesehatan dan Diagnostik",
            "Tantangan Etika dan Bias Algoritma Kecerdasan Buatan",
        ],
        "contents": [
            (
                "Kecerdasan buatan atau AI kini mulai merambah berbagai sektor, "
                "mulai dari layanan kesehatan hingga finansial. Kemampuan machine "
                "learning dalam menganalisis data besar memberikan wawasan yang "
                "belum pernah ada sebelumnya."
            ),
            (
                "Meski menjanjikan efisiensi tinggi, adopsi AI juga membawa "
                "tantangan etika. Regulasi mengenai privasi data dan bias "
                "algoritma menjadi topik diskusi utama di kalangan pakar "
                "teknologi global."
            ),
        ],
    },
    "Ekonomi Digital": {
        "titles": [
            "Transformasi Sistem Pembayaran Digital di Era Modern",
            "UMKM Go Digital: Tantangan dan Peluang Ekonomi Baru",
        ],
        "contents": [
            (
                "Pertumbuhan ekonomi digital di Indonesia menunjukkan tren "
                "positif. Hal ini didorong oleh penetrasi internet yang semakin "
                "merata serta tingginya tingkat adopsi sistem pembayaran digital "
                "di kalangan masyarakat."
            ),
            (
                "E-commerce dan layanan finansial digital terus mendominasi "
                "lanskap ekonomi baru. Transformasi ini tidak hanya memudahkan "
                "konsumen tetapi juga membuka peluang besar bagi Usaha Mikro, "
                "Kecil, dan Menengah (UMKM)."
            ),
        ],
    },
    "Olahraga": {
        "titles": [
            "Persiapan Atlet Nasional Menuju Kejuaraan Asia",
            "Manfaat Olahraga Rutin Bagi Pekerja Kantoran yang Sibuk",
        ],
        "contents": [
            (
                "Ajang olahraga nasional kembali digelar dengan antusiasme tinggi "
                "dari para pendukung. Persiapan para atlet yang matang diharapkan "
                "mampu memecahkan rekor-rekor baru pada turnamen tahun ini."
            ),
            (
                "Pentingnya olahraga bagi kesehatan terus dikampanyekan. Berbagai "
                "komunitas lari dan bersepeda semakin menjamur di kota-kota besar, "
                "menunjukkan kesadaran masyarakat akan gaya hidup aktif."
            ),
        ],
    },
    "Kesehatan Mental": {
        "titles": [
            "Pentingnya Menjaga Kewarasan Psikologis di Era Digital",
            "Mengenal Gejala Burnout di Tempat Kerja dan Cara Mengatasinya",
        ],
        "contents": [
            (
                "Kesadaran masyarakat tentang pentingnya kesehatan mental "
                "semakin meningkat. Banyak perusahaan kini mulai menyediakan "
                "fasilitas konseling dan hari libur khusus untuk menjaga "
                "kesejahteraan psikologis karyawan mereka."
            ),
            (
                "Menghilangkan stigma terhadap gangguan kesehatan mental adalah "
                "langkah pertama menuju masyarakat yang lebih sehat. Konsultasi "
                "dengan psikolog kini semakin mudah diakses berkat layanan "
                "telemedicine."
            ),
        ],
    },
    "Politik": {
        "titles": [
            "Dinamika Pemilu dan Peta Koalisi Partai Politik Terkini",
            "Pentingnya Partisipasi Gen Z dalam Demokrasi Indonesia",
        ],
        "contents": [
            (
                "Dinamika politik menjelang pemilihan umum mulai terasa memanas. "
                "Para kandidat dan partai politik sibuk merumuskan strategi "
                "kampanye dan manifesto untuk menarik simpati para pemilih muda."
            ),
            (
                "Transparansi dan akuntabilitas pemerintah terus menjadi sorotan "
                "publik. Partisipasi aktif masyarakat sipil dalam mengawasi "
                "kebijakan negara sangat penting untuk menjaga iklim demokrasi "
                "yang sehat."
            ),
        ],
    },
    "Budaya Nusantara": {
        "titles": [
            "Melestarikan Kain Tenun di Tengah Gempuran Fashion Cepat",
            "Pesona Seni Tari Tradisional yang Mulai Mendunia",
        ],
        "contents": [
            (
                "Kekayaan budaya Nusantara merupakan warisan leluhur yang harus "
                "terus dilestarikan. Festival seni dan budaya daerah tidak hanya "
                "menarik wisatawan, tetapi juga menjadi ajang edukasi bagi "
                "generasi muda."
            ),
            (
                "Kain tenun dan batik dari berbagai daerah kembali mendapatkan "
                "tempat di industri fashion internasional. Kolaborasi antara "
                "pengrajin lokal dan desainer modern sukses menciptakan tren "
                "yang unik dan bernilai jual tinggi."
            ),
        ],
    },
    "Pendidikan": {
        "titles": [
            "Tantangan Akses Pendidikan Berkualitas di Daerah Pelosok",
            "Pentingnya Kurikulum Berbasis Keterampilan dan Pemikiran Kritis",
        ],
        "contents": [
            (
                "Sistem pendidikan terus beradaptasi dengan kebutuhan zaman "
                "modern. Kurikulum yang berfokus pada pemikiran kritis dan "
                "literasi digital diharapkan mampu mencetak lulusan yang siap "
                "bersaing di pasar kerja global."
            ),
            (
                "Akses terhadap pendidikan berkualitas masih menjadi tantangan "
                "di daerah pelosok. Pemerintah dan berbagai LSM terus berupaya "
                "menyediakan fasilitas dan tenaga pengajar yang memadai untuk "
                "pemerataan pendidikan."
            ),
        ],
    },
    "Lingkungan Hidup": {
        "titles": [
            "Ancaman Pemanasan Global dan Transisi Energi Terbarukan",
            "Menggalakkan Gaya Hidup Bebas Plastik di Wilayah Perkotaan",
        ],
        "contents": [
            (
                "Isu pemanasan global dan kelestarian lingkungan hidup kini "
                "menjadi sorotan utama. Transisi menuju energi terbarukan dan "
                "pengurangan emisi karbon adalah langkah krusial untuk "
                "menyelamatkan bumi dari krisis iklim."
            ),
            (
                "Pengelolaan sampah plastik masih menjadi masalah besar di "
                "wilayah perkotaan. Inisiatif daur ulang dan pengurangan "
                "penggunaan plastik sekali pakai terus digalakkan oleh berbagai "
                "komunitas peduli lingkungan."
            ),
        ],
    },
    "Inovasi Startup": {
        "titles": [
            "Dinamika Pendanaan Venture Capital untuk Startup Tahap Awal",
            "Startup Agritech yang Siap Mengubah Wajah Pertanian Lokal",
        ],
        "contents": [
            (
                "Ekosistem startup di tanah air terus melahirkan inovasi-inovasi "
                "baru. Banyak perusahaan rintisan kini fokus memecahkan masalah "
                "lokal melalui pendekatan teknologi yang aplikatif dan efisien."
            ),
            (
                "Dukungan pendanaan dari venture capital untuk startup tahap awal "
                "kembali bergairah. Investor kini lebih selektif dan mencari "
                "startup yang memiliki jalur profitabilitas yang jelas dan model "
                "bisnis yang berkelanjutan."
            ),
        ],
    },
}


def render_progress_bar(done: int, total: int, width: int = 20) -> None:
    """Print an in-place progress bar: ``[####----] 45%``."""
    fraction = done / total if total else 1.0
    filled = int(width * fraction)
    bar = "#" * filled + "-" * (width - filled)

    sys.stdout.write(f"\r[{bar}] {int(fraction * 100):>3}%")
    sys.stdout.flush()


def seed(
    count: int,
    batch_size: int,
    locale: str | None = None,
) -> int:
    from app.infrastructure.database.repositories.article_repository import (
        SqlAlchemyArticleRepository,
    )
    from app.infrastructure.database.session import get_session_factory
    from app.infrastructure.messaging.task_publisher import get_task_publisher

    settings = get_settings()

    configure_logging(
        settings.log_level,
        settings.log_format,
    )

    fake = Faker(locale or settings.faker_locale)
    session_factory = get_session_factory()
    publisher = get_task_publisher()

    print("Starting article seeder...\n")
    print(f"Generating {count} articles...\n")

    started = time.perf_counter()
    created = 0
    session = session_factory()

    try:
        repository = SqlAlchemyArticleRepository(session)

        for index in range(1, count + 1):
            topic = random.choice(_TOPICS)

            # Ambil judul dan konten yang masuk akal dari template.
            selected_title = random.choice(
                CONTENT_TEMPLATES[topic]["titles"]
            )
            selected_content = random.choice(
                CONTENT_TEMPLATES[topic]["contents"]
            )

            # Tambahkan sedikit variasi agar tidak 100% duplikat jika count-nya
            # besar.
            unique_suffix = fake.random_int(
                min=1000,
                max=9999,
            )

            final_title = f"{selected_title} - #{unique_suffix}"

            article = Article(
                title=final_title,
                content=selected_content,
                author=fake.name(),
            )

            repository.save(article)
            publisher.publish_processing(str(article.id))

            created += 1

            if index % batch_size == 0 or index == count:
                render_progress_bar(index, count)

    finally:
        session.close()

    elapsed = time.perf_counter() - started

    print(f"\n\nSuccessfully created {created} articles.")
    print(f"Tasks dispatched: {created}")
    print(f"Elapsed: {elapsed:.2f}s")

    return created


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.cli",
        description=(
            "Management CLI for the Article Ingestion & Vector Search API"
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    seed_parser = subparsers.add_parser(
        "seed",
        help=(
            "Generate dummy articles with templates and "
            "dispatch processing tasks"
        ),
    )

    seed_parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of articles to generate (default: 100)",
    )

    seed_parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Commit / progress chunk size (default: 50)",
    )

    seed_parser.add_argument(
        "--locale",
        type=str,
        default=None,
        help="Faker locale, e.g. id_ID (default: FAKER_LOCALE env or id_ID)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "seed":
        if args.count < 1:
            parser.error("--count must be >= 1")

        if args.batch_size < 1:
            parser.error("--batch-size must be >= 1")

        seed(
            count=args.count,
            batch_size=args.batch_size,
            locale=args.locale,
        )

        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())