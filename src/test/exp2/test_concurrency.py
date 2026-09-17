import sys
import threading

from main.exp2.board import Board


def test_many_readers_hold_the_lock_at_once():
    b = Board()
    b.post("user", "root")
    n = 4
    gate = threading.Barrier(n, timeout=3)
    inside = []

    def reader():
        with b.lock.read():
            gate.wait()
            inside.append(1)

    ts = [threading.Thread(target=reader) for _ in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert len(inside) == n


def test_a_write_waits_for_readers_to_finish():
    b = Board()
    b.post("user", "root")
    wrote = threading.Event()

    def writer():
        with b.lock.write():
            wrote.set()

    t = threading.Thread(target=writer)
    with b.lock.read():
        t.start()
        assert not wrote.wait(0.2)

    t.join()
    assert wrote.is_set()


def test_a_read_waits_for_a_write_to_finish():
    b = Board()
    b.post("user", "root")
    read_done = threading.Event()

    def reader():
        with b.lock.read():
            read_done.set()

    t = threading.Thread(target=reader)
    with b.lock.write():
        t.start()
        assert not read_done.wait(0.2)

    t.join()
    assert read_done.is_set()


def test_nested_reads_do_not_deadlock_behind_a_waiting_writer():
    b = Board()
    b.post("user", "root")
    wrote = threading.Event()

    def writer():
        with b.lock.write():
            wrote.set()

    with b.lock.read():
        t = threading.Thread(target=writer)
        t.start()
        wrote.wait(0.1)
        # render() nests threads()/walk()/outline() inside this outer read
        assert b.render()

    t.join()
    assert wrote.is_set()


def test_concurrent_posts_to_one_subtree_all_land():
    b = Board()
    root = b.post("user", "root")

    def worker(n):
        for i in range(50):
            b.post("user", f"{n}-{i}", parent=root.id)

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    kids = b[root.id].children
    assert len(kids) == 400
    assert len(set(kids)) == 400
    assert len(b.walk(root.id)) == 401


def test_every_message_stays_reachable_while_posts_arrive():
    b = Board()
    done = threading.Event()
    bad = []
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)

    def writer():
        try:
            for i in range(120):
                r = b.post("user", f"q{i}")
                b.post("assistant", f"a{i}", parent=r.id)
        finally:
            done.set()

    def reader():
        while not done.is_set():
            with b.lock.read():
                reachable = {m.id for root in b.threads() for m in b.walk(root.id)}
                if reachable != set(b.msgs):
                    bad.append(set(b.msgs) - reachable)

    w, r = threading.Thread(target=writer), threading.Thread(target=reader)
    try:
        w.start()
        r.start()
        w.join()
        r.join()
    finally:
        sys.setswitchinterval(old)

    assert not bad
    assert len(b.threads()) == 120


def test_render_stays_consistent_while_posts_arrive():
    b = Board()
    root = b.post("user", "root")
    done = threading.Event()
    errors = []

    def writer():
        try:
            for i in range(150):
                b.post("user", f"x{i}", parent=root.id)
        finally:
            done.set()

    def reader():
        try:
            while not done.is_set():
                for m in b.render():
                    assert isinstance(m["content"], str)
        except Exception as e:
            errors.append(e)

    w, r = threading.Thread(target=writer), threading.Thread(target=reader)
    w.start()
    r.start()
    w.join()
    r.join()

    assert not errors
    assert len(b[root.id].children) == 150
