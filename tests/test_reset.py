import config
import reset
import workflow
from workflow import Interrupt, Locator, Target


def test_reset_forgets_heals_but_keeps_compiled_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "WORKFLOWS_DIR", tmp_path)
    wf = workflow.load(config.ROOT / "examples" / "pay-interstate-tax.v1.json")
    workflow.save(wf)
    recompiled = wf.model_copy(deep=True, update={"version": 2})
    workflow.save(recompiled)
    healed = wf.model_copy(deep=True, update={"version": 3})
    healed.steps[3].healed = [{"version": 3, "situation": "moved", "path": "sam+spark"}]
    workflow.save(healed)
    modal = wf.model_copy(deep=True, update={"version": 4})
    modal.interrupts = [Interrupt(id="i1", target=Target(locators=[Locator(kind="role", role="button", name="Accept all")]))]
    workflow.save(modal)
    assert [p.name for p in reset.healed_versions()] == ["pay-interstate-tax.v3.json", "pay-interstate-tax.v4.json"]
