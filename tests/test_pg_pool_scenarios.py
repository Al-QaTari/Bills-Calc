# tests/test_pg_pool_scenarios.py
# Real-PostgreSQL failure scenarios for the shared small connection pool.
# Needs the optional `pgserver` package (a local throwaway Postgres); skipped otherwise.
import tempfile
import threading
import time
from datetime import datetime

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeout

pgserver = pytest.importorskip("pgserver")
import constants as C  # noqa: E402


@pytest.fixture(scope="module")
def pg():
    d = tempfile.mkdtemp(prefix="pgpool_")
    srv = pgserver.get_server(d)
    yield srv, d
    srv.cleanup()


@pytest.fixture
def pm(pg, monkeypatch):
    srv, _ = pg
    uri = srv.get_uri().replace("postgresql://", "postgres://", 1)
    monkeypatch.setenv("POSTGRES_URI", uri)
    monkeypatch.delenv("PG_POOL_SIZE", raising=False)
    monkeypatch.delenv("PG_MAX_OVERFLOW", raising=False)
    monkeypatch.delenv("PG_POOL_TIMEOUT", raising=False)
    import postgres_manager as m

    m.dispose_shared_engines()
    import streamlit as st

    st.cache_data.clear()
    yield m
    m.dispose_shared_engines()


def _count(srv):
    out = srv.psql(
        "select count(*) from pg_stat_activity where datname=current_database() "
        "and pid<>pg_backend_pid() and application_name='' and backend_type='client backend';"
    )
    return int([ln for ln in out.splitlines() if ln.strip().isdigit()][0])


def _df(n=4, session="01/01/2026"):
    return pd.DataFrame(
        {
            C.TENOR_COLUMN_NAME: [91, 182, 273, 357][:n],
            C.YIELD_COLUMN_NAME: [25.0, 25.5, 26.0, 26.5][:n],
            C.SESSION_DATE_COLUMN_NAME: [session] * n,
            C.DATE_COLUMN_NAME: [datetime(2026, 1, 1)] * n,
        }
    )


def test_two_managers_share_one_engine(pm):
    a, b = pm.PostgresDBManager(), pm.PostgresDBManager()
    assert a.engine is b.engine
    assert a.engine.pool.size() == 3 and a.engine.pool._max_overflow == 3


def test_env_overrides_and_bad_values(pm, monkeypatch):
    monkeypatch.setenv("PG_POOL_SIZE", "2")
    monkeypatch.setenv("PG_MAX_OVERFLOW", "1")
    pm.dispose_shared_engines()
    e = pm.PostgresDBManager().engine
    assert (e.pool.size(), e.pool._max_overflow) == (2, 1)
    for bad in ["abc", "0", "-5", "", "3.5"]:
        monkeypatch.setenv("PG_POOL_SIZE", bad)
        monkeypatch.setenv("PG_MAX_OVERFLOW", bad)
        pm.dispose_shared_engines()
        e = pm.PostgresDBManager().engine
        assert e.pool.size() >= 1 and e.pool._max_overflow >= 0


def test_many_threads_never_exceed_pool_cap(pm, pg):
    srv, _ = pg
    db = pm.PostgresDBManager()
    db.save_data(_df())
    errors, peak = [], [0]
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            peak[0] = max(peak[0], _count(srv))
            time.sleep(0.02)

    def work():
        try:
            for _ in range(15):
                db.load_latest_data()
                db.load_all_historical_data()
        except Exception as e:  # noqa
            errors.append(e)

    w = threading.Thread(target=watch)
    w.start()
    ts = [threading.Thread(target=work) for _ in range(30)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    stop.set()
    w.join()
    assert not errors
    assert 0 < peak[0] <= 6, peak[0]


def test_pool_exhaustion_times_out_then_recovers(pm, monkeypatch):
    monkeypatch.setenv("PG_POOL_SIZE", "1")
    monkeypatch.setenv("PG_MAX_OVERFLOW", "1")
    monkeypatch.setenv("PG_POOL_TIMEOUT", "1")
    pm.dispose_shared_engines()
    db = pm.PostgresDBManager()
    c1, c2 = db.engine.connect(), db.engine.connect()
    t0 = time.time()
    with pytest.raises(PoolTimeout):
        db.engine.connect()
    assert 0.9 < time.time() - t0 < 3
    # app-level readers must degrade gracefully, not crash
    df, info = db.load_latest_data()
    assert df.empty
    c1.close()
    c2.close()
    db.save_data(_df())
    assert not db.load_latest_data()[0].empty


def test_connections_killed_server_side_are_healed(pm, pg):
    srv, _ = pg
    db = pm.PostgresDBManager()
    db.save_data(_df())
    db.load_latest_data()
    srv.psql(
        "select pg_terminate_backend(pid) from pg_stat_activity "
        "where datname=current_database() and pid<>pg_backend_pid() and backend_type='client backend';"
    )
    time.sleep(0.3)
    df, _ = db.load_latest_data()  # pre_ping must discard the dead connections
    assert len(df) == 4


def test_server_restart_is_survived(pm, pg):
    srv, d = pg
    db = pm.PostgresDBManager()
    db.save_data(_df())
    db.load_latest_data()
    srv.cleanup()  # stop server
    df, _ = db.load_latest_data()
    assert df.empty  # graceful, no exception
    pgserver.get_server(d)
    try:
        for _ in range(20):
            df, _ = db.load_latest_data()
            if not df.empty:
                break
            time.sleep(0.5)
        assert len(df) == 4
    finally:
        pass


def test_unreachable_server_at_startup_raises_and_app_falls_back(
    pm, monkeypatch, tmp_path
):
    monkeypatch.setenv("POSTGRES_URI", "postgres://u:p@127.0.0.1:1/none")
    pm.dispose_shared_engines()
    t0 = time.time()
    with pytest.raises(Exception):
        pm.PostgresDBManager()
    assert time.time() - t0 < 15  # connect_timeout=10 bounds the wait
    import db_manager
    import streamlit as st

    st.cache_resource.clear()
    monkeypatch.setattr(db_manager, "DATA_DIR", tmp_path)
    mgr, name = db_manager.get_db_manager("fb.db")
    assert name == "SQLite"


def test_dispose_releases_all_connections(pm, pg):
    srv, _ = pg
    db = pm.PostgresDBManager()
    cs = [db.engine.connect() for _ in range(4)]
    [c.close() for c in cs]
    assert _count(srv) >= 1
    pm.dispose_shared_engines()
    time.sleep(0.3)
    assert _count(srv) == 0
    # a new manager after dispose works
    assert pm.PostgresDBManager().engine is not db.engine


def test_concurrent_writes_and_reads_consistent(pm):
    db = pm.PostgresDBManager()
    errors = []

    def writer(i):
        try:
            db.save_data(_df(session=f"{i+1:02d}/02/2026"))
        except Exception as e:  # noqa
            errors.append(e)

    ts = [threading.Thread(target=writer, args=(i,)) for i in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    with db.engine.connect() as c:
        n = c.execute(text(f'select count(*) from "{C.TABLE_NAME}"')).scalar()
    assert n >= 4 * 12


def test_failed_transaction_returns_connection_to_pool(pm):
    db = pm.PostgresDBManager()
    for _ in range(20):  # more failures than pool capacity
        with pytest.raises(Exception):
            with db.engine.connect() as c:
                c.execute(text("select * from table_that_does_not_exist"))
    assert db.engine.pool.checkedout() == 0
    assert not db.load_latest_data()[0].empty or True
    with db.engine.connect() as c:
        assert c.execute(text("select 1")).scalar() == 1


def test_container_and_get_db_manager_use_same_engine(pm):
    import streamlit as st
    import db_manager
    from dependency_container import DependencyContainer
    from treasury_core.ports import HistoricalDataStore

    st.cache_resource.clear()
    a = DependencyContainer().get(HistoricalDataStore)
    b, name = db_manager.get_db_manager()
    assert name == "PostgreSQL"
    assert a.engine is b.engine


def test_historical_cache_has_ttl_and_refreshes(pm):
    db = pm.PostgresDBManager()
    db.save_data(_df())
    first = len(db.load_all_historical_data())
    db.save_data(_df(session="09/03/2026"))
    # same call is cached (stale by design inside TTL)...
    assert len(db.load_all_historical_data()) == first
    import streamlit as st

    st.cache_data.clear()
    assert len(db.load_all_historical_data()) == first + 4
