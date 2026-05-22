import getpass
import os
from copy import deepcopy

import pandas as pd


def normalize_metadata_source(config):
    source = deepcopy(config.get("metadata_source") or {})
    if not source and ("db" in config or "database" in config or "tables" in config):
        source = {
            "type": "db",
            "db": deepcopy(config.get("db") or config.get("database")),
            "tables": deepcopy(config.get("tables") or {}),
        }

    if isinstance(source, str):
        source = {"type": source}

    if not source:
        raise KeyError(
            "Config must include DB metadata settings. Add `metadata_source` with "
            "`type: db`, `db`, and `tables` sections."
        )

    if "type" not in source:
        if "db" in source or "database" in source or "tables" in source:
            source["type"] = "db"
        else:
            raise KeyError(
                "metadata_source must include `type: db` or DB/table settings."
            )

    source["type"] = str(source["type"]).strip().lower()
    return source


def _quote_identifier(identifier):
    return '"' + str(identifier).replace('"', '""') + '"'


def split_qualified_table(qualified, default_schema="public"):
    qualified = str(qualified).strip().strip('"').strip("'")
    if not qualified:
        raise ValueError("Table name must not be empty.")

    if "." in qualified:
        schema, table = qualified.split(".", 1)
    else:
        schema, table = default_schema, qualified

    schema = schema.strip().strip('"')
    table = table.strip().strip('"')
    if not schema or not table:
        raise ValueError(f"Invalid table name: {qualified!r}")

    return schema, table


def build_table_queries(qualified):
    schema, table = split_qualified_table(qualified)
    quoted_table = f"{_quote_identifier(schema)}.{_quote_identifier(table)}"
    return (
        f"SELECT COUNT(*) AS n FROM {quoted_table}",
        f"SELECT * FROM {quoted_table}",
    )


def _db_config_from_source(source):
    db_config = source.get("db") or source.get("database")
    if not db_config:
        raise KeyError("metadata_source must include a 'db' or 'database' section.")
    return db_config


def _db_value(db_config, *keys, default=None):
    for key in keys:
        if key in db_config and db_config[key] is not None:
            return db_config[key]
    return default


def _is_missing(value):
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "none", "null"}:
        return True
    return False


def _prompt_value(label, secret=False):
    prompt = f"{label}: "
    try:
        if secret:
            value = getpass.getpass(prompt)
        else:
            value = input(prompt)
    except (EOFError, OSError) as exc:
        raise RuntimeError(
            f"Missing required config value for {label!r}, and interactive input "
            "is not available."
        ) from exc

    if _is_missing(value):
        raise ValueError(f"{label} must not be empty.")
    return value


def _db_value_or_prompt(db_config, label, *keys, secret=False):
    value = _db_value(db_config, *keys)
    if _is_missing(value):
        value = _prompt_value(label, secret=secret)
    return value


def create_metadata_engine(source):
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.engine import URL
    except ImportError as exc:
        raise RuntimeError(
            "DB metadata loading requires SQLAlchemy. Install `sqlalchemy` and the "
            "appropriate database driver, for example `psycopg2-binary` for PostgreSQL."
        ) from exc

    db_config = _db_config_from_source(source)
    url = db_config.get("url")
    if url:
        return create_engine(url, pool_pre_ping=True)

    driver = _db_value(db_config, "driver", default="postgresql+psycopg2")
    username = _db_value_or_prompt(db_config, "DB user", "user", "username")
    host = _db_value_or_prompt(db_config, "DB host", "host")
    port = int(_db_value_or_prompt(db_config, "DB port", "port"))
    database = _db_value_or_prompt(db_config, "DB database", "database", "db", "name")
    password = _db_value(db_config, "password", "pwd")
    password_env = db_config.get("password_env") or db_config.get("pwd_env")
    if password is None and password_env:
        password = os.environ.get(password_env)
    if _is_missing(password):
        password = _prompt_value("DB password", secret=True)

    sqlalchemy_url = URL.create(
        drivername=driver,
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
    )
    return create_engine(sqlalchemy_url, pool_pre_ping=True)


def extract_db_table(engine, table_name, verbose=False, label=None):
    try:
        from sqlalchemy import text
    except ImportError as exc:
        raise RuntimeError(
            "DB metadata loading requires SQLAlchemy. Install `sqlalchemy` first."
        ) from exc

    count_sql, select_sql = build_table_queries(table_name)
    if verbose:
        n = pd.read_sql(text(count_sql), engine)["n"].iloc[0]
        prefix = f"{label} " if label else ""
        print(f"{prefix}rows: {n}")

    return pd.read_sql(text(select_sql), engine)


def _get_table_name(source, table_key):
    tables = source.get("tables") or {}
    aliases = {
        "hids_all": ["hids_all", "hutom_id", "HUTOM_ID"],
        "video_meta": ["video_meta", "VIDEO_META"],
        "image_meta": ["image_meta", "IMAGE_META"],
    }
    for key in aliases.get(table_key, [table_key]):
        if key in tables and not _is_missing(tables[key]):
            return tables[key]
        if key in tables:
            return _prompt_value(f"DB table for {table_key}")
    raise KeyError(f"metadata_source.tables must include '{table_key}'.")


def load_shared_metadata(config, specs, verbose=False):
    source = normalize_metadata_source(config)

    if source["type"] != "db":
        raise ValueError(f"Unsupported metadata_source.type: {source['type']}")

    engine = create_metadata_engine(source)
    return {
        output_key: extract_db_table(
            engine,
            _get_table_name(source, table_key),
            verbose=verbose,
            label=table_key,
        )
        for output_key, table_key in specs
    }
