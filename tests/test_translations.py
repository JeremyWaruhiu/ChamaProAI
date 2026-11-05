"""scripts/translations.py: the sheet, and what comes back from it."""
import csv
import json
import shutil

import pytest
import yaml

import translations as tr
from chamapro.api import member_text
from chamapro.conversation import templates


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """The three files import writes, as copies. Reading the templates as they really are."""
    table = tmp_path / "templates.yaml"
    shutil.copy(templates.PATH, table)
    strings, why = tmp_path / "strings.kik.json", tmp_path / "member_text_kik.json"
    strings.write_text("{}"), why.write_text("{}")
    monkeypatch.setattr(tr, "STRINGS_KIK", strings)
    monkeypatch.setattr(member_text, "KIKUYU_PATH", why)
    monkeypatch.setattr(tr, "write_templates", lambda t, path=table, real=tr.write_templates: real(t, path))
    return tmp_path, table, strings, why


def sheet(path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fill(path, words):
    rows = sheet(path)
    for r in rows:
        if r["id"] in words:
            r["kikuyu"] = words[r["id"]]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=tr.COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def test_the_sheet_in_the_repository_is_up_to_date(tmp_path):
    fresh = tmp_path / "fresh.csv"
    tr.export(fresh)
    wanted = [{k: r[k] for k in ("id", "where", "english", "slots")} for r in sheet(fresh)]
    have = [{k: r[k] for k in ("id", "where", "english", "slots")} for r in sheet(tr.CSV_PATH)]
    assert have == wanted, "run scripts/translations.py export"


def test_the_sheet_holds_everything_it_should_and_says_where_each_goes(tmp_path):
    path = tmp_path / "k.csv"
    tr.export(path)
    rows = {r["id"]: r for r in sheet(path)}
    assert list(sheet(path)[0]) == list(tr.COLUMNS)
    assert all(r["kikuyu"] == "" for r in rows.values())
    for tid in templates.load():
        assert f"template.{tid}" in rows
    assert rows["template.G1"]["where"] == "bot speech" and rows["template.G1"]["slots"] == "first_name sacco_name"
    assert rows["template.ACTION_REVIEW"]["where"] == "button"
    assert rows["chat.stage.deciding"] == {"id": "chat.stage.deciding", "where": "screen text", "english": "Deciding", "slots": "", "kikuyu": ""}
    assert rows["chat.outcome.balanceAfter"]["english"] == "After"
    assert rows["button.yes"]["where"] == "button" and rows["button.no"]["english"] == "No"
    assert rows["chat.months.many"]["slots"] == "n"
    assert rows["why.reason.approve"]["where"] == "Why sentence"
    assert rows["why.reason.approve"]["slots"] == "amount instalment term"
    assert rows["why.check.membership"]["slots"] == "minimum months"
    assert "chat.chooseLanguage" not in rows


def test_a_filled_sheet_goes_where_each_line_belongs(repo):
    tmp, table, strings, why = repo
    path = tmp / "k.csv"
    tr.export(path)
    before = table.read_text(encoding="utf-8")
    fill(path, {"template.R1": 'Ũkwenda mbeca ciigana?', "template.C2": "Mũcara waku nĩ {monthly_income}, nĩ guo?",
                "template.G1": "Wĩ mwega {first_name}. {sacco_name}.", "chat.stage.deciding": "Gũtua", "button.yes": "Ĩĩ, nĩ wega",
                "chat.months.many": "Mĩeri {n}", "why.reason.clarify": "Nĩ tũkwenda kũmenya ũngĩ.",
                "why.check.membership": "Mĩeri {months} ({minimum})."})
    assert tr.import_filled(path) == 0
    assert json.loads(strings.read_text(encoding="utf-8")) == {"chat.stage.deciding": "Gũtua", "button.yes": "Ĩĩ, nĩ wega", "chat.months.many": "Mĩeri {n}"}
    assert json.loads(why.read_text(encoding="utf-8")) == {"why.reason.clarify": "Nĩ tũkwenda kũmenya ũngĩ.",
                                                           "why.check.membership": "Mĩeri {months} ({minimum})."}
    after = table.read_text(encoding="utf-8")
    written = templates.check(yaml.safe_load(after))
    assert written["C2"]["kik"] == "Mũcara waku nĩ {monthly_income}, nĩ guo?" and written["C4"]["kik"] == ""
    assert {k: v["en"] for k, v in written.items()} == {k: v["en"] for k, v in yaml.safe_load(before).items()}
    assert after.startswith("# Every word the bot says.")       # the comments stay


@pytest.mark.parametrize("rid, words, says", [
    ("template.C2", "Mũcara waku?", "missing {monthly_income}"),
    ("why.reason.approve", "KSh {amount:,} na {term}", "missing {instalment}"),
    ("template.R1", "Ũkwenda {amount}?", "has {amount}"),
    ("chat.months.one", "Mweri ũmwe", "missing {n}"),
    ("template.R1", "Ũkwenda {amount?", "does not close"),
])
def test_a_line_with_the_wrong_slots_stops_everything(repo, capsys, rid, words, says):
    tmp, table, strings, why = repo
    path = tmp / "k.csv"
    tr.export(path)
    before = table.read_text(encoding="utf-8")
    fill(path, {rid: words, "chat.stage.deciding": "Gũtua"})
    assert tr.import_filled(path) == 1
    assert says in capsys.readouterr().err
    assert table.read_text(encoding="utf-8") == before and strings.read_text() == "{}" and why.read_text() == "{}"


def test_a_slot_written_without_its_format_is_still_that_slot(repo):
    tmp, *_ = repo
    path = tmp / "k.csv"
    tr.export(path)
    fill(path, {"why.check.deposits_on_record.met": "Mbeca ciaku nĩ KSh {deposits}."})
    assert tr.import_filled(path) == 0


def test_what_is_left_empty_is_reported_and_stays_english(repo, capsys):
    tmp, *_ = repo
    path = tmp / "k.csv"
    tr.export(path)
    fill(path, {"template.R1": "Ũkwenda mbeca ciigana?"})
    assert tr.import_filled(path) == 0
    out = capsys.readouterr().out
    assert "1 translated" in out and "template.G1" in out and "still in English" in out


def test_a_line_that_no_longer_exists_or_has_moved_on_is_refused(repo, capsys):
    tmp, *_ = repo
    path = tmp / "k.csv"
    tr.export(path)
    rows = sheet(path)
    rows.append({"id": "template.GONE", "where": "bot speech", "english": "x", "slots": "", "kikuyu": "y"})
    rows[0]["english"], rows[0]["kikuyu"] = "An older wording", "Wĩ mwega {first_name}. {sacco_name}."
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=tr.COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    assert tr.import_filled(path) == 1
    err = capsys.readouterr().err
    assert "template.GONE" in err and "has changed since" in err


# --- What a member then reads ----------------------------------------------------------------

def test_why_sentences_come_in_kikuyu_where_they_have_been_translated(monkeypatch):
    monkeypatch.setattr(member_text, "kikuyu", lambda: {
        "why.check.membership": "Mĩeri {months}, mĩnima {minimum}.", "why.driver.favour": "{what}: nĩ wega.",
        "why.phrase.household_size": "Andũ a mũcii", "why.reason.clarify": "Nĩ tũkwenda kũmenya ũngĩ."})
    full = {"reason": "We need a little more from you before we can answer.", "reason_code": "clarify", "reason_values": {},
            "risk_class": "Low", "contributions": [{"feature": "household_size", "value": 4, "shap": 0.2}],
            "trace": {"checks": [{"check": "membership", "passed": True, "values": {"months": 60, "minimum": 6}},
                                 {"check": "no_arrears", "passed": True, "values": {}}]}}
    kik = member_text.plain_explain(full, "kik")
    assert kik["reason"] == "Nĩ tũkwenda kũmenya ũngĩ."
    assert kik["checks"][0]["text"] == "Mĩeri 60, mĩnima 6."
    assert kik["checks"][1]["text"] == "You have no loan payment outstanding."      # not translated yet
    assert kik["drivers"] == ["Andũ a mũcii: nĩ wega."]
    en = member_text.plain_explain(full, "en")
    assert en["reason"] == full["reason"] and en["checks"][0]["text"] == "You have been a member for 60 months. The minimum is 6."
    assert en["drivers"] == ["The size of your household counts in your favour."]


def test_a_turn_from_before_the_figures_were_kept_keeps_its_english_reason(monkeypatch):
    monkeypatch.setattr(member_text, "kikuyu", lambda: {"why.reason.approve": "Nĩ wega {amount}."})
    full = {"reason": "You can have KSh 1 now.", "reason_code": "approve", "risk_class": "Low", "contributions": [], "trace": {"checks": []}}
    assert member_text.plain_explain(full, "kik")["reason"] == "You can have KSh 1 now."
