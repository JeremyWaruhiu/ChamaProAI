

def test_cpu_threads_come_from_the_container_quota(tmp_path, monkeypatch):
    from chamapro import config
    real = config.Path

    def fake(files):
        def path(p, *a):
            p = str(p)
            return real(files[p]) if p in files else real(tmp_path / "absent")
        return path

    v2 = tmp_path / "cpu.max"
    for text, want in [("200000 100000\n", 2), ("150000 100000", 2), ("max 100000", None), ("50000 100000", 1)]:
        v2.write_text(text)
        monkeypatch.setattr(config, "Path", fake({"/sys/fs/cgroup/cpu.max": v2}))
        assert config._cgroup_cpus() == want, text
    q, per = tmp_path / "q", tmp_path / "p"
    q.write_text("400000\n"), per.write_text("100000\n")
    monkeypatch.setattr(config, "Path", fake({"/sys/fs/cgroup/cpu/cpu.cfs_quota_us": q,
                                              "/sys/fs/cgroup/cpu/cpu.cfs_period_us": per}))
    assert config._cgroup_cpus() == 4
    q.write_text("-1")
    assert config._cgroup_cpus() is None
    monkeypatch.setattr(config, "Path", fake({}))
    assert config._cgroup_cpus() is None
