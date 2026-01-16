
import typer

from config import load_config
from discover import run as run_discover, feed as run_feed
from ingest import run as run_ingest

app = typer.Typer(context_settings={"help_option_names": ["-h", "--help"]})


@app.command()
def discover(config: str = "config.yaml"):
    run_discover(config)


@app.command()
def feed(config: str = "config.yaml"):
    run_feed(config)


@app.command()
def ingest_porla(config: str = "config.yaml"):
    run_ingest(config)


@app.command()
def initdb(config: str = "config.yaml"):
    from db import get_engine, init_db
    cfg = load_config(config)
    engine = get_engine(cfg.storage.db_path)
    init_db(engine)


if __name__ == "__main__":
    app()
