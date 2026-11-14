"""Demo scene: price an installment plan through the live API docs.
Start the API first:  cd backend && uv run uvicorn aios.entrypoints.api:app --port 8731
Run:  python docs/demo/scene.py
Then: python ~/.claude/skills/demo-gif/scripts/compose.py docs/demo/build --out docs/demo.gif
"""
import os, sys; sys.path.insert(0, os.path.expanduser("~/.claude/skills/demo-gif/scripts"))
from pathlib import Path
from director import Director, run

BODY = ('{"list_price":"4500000","down_payment_pct":"10","years":8,"frequency":"quarterly",'
        '"delivery_payment_pct":"5","discount_pct":"2"}')

async def scene(d: Director):
    p = d.page
    await d.goto("http://localhost:8731/docs", settle=1.5)
    await p.locator("#operations-pricing-installment_plan_pricing_installments_post").wait_for()
    await d.caption("Open the pricing endpoint", step=1)
    op = p.locator("#operations-pricing-installment_plan_pricing_installments_post .opblock-summary-control")
    await d.click(op)
    await d.click(p.get_by_role("button", name="Try it out"))
    await d.caption("Describe the payment plan", step=2)
    box = p.locator("textarea.body-param__text")
    await d.type(box, BODY, cps=45)
    await d.hold(0.6)
    await d.caption("Run the exact Decimal engine", step=3)
    await d.click(p.get_by_role("button", name="Execute"))
    await d.fast(p.locator(".live-responses-table .response-col_status").first.wait_for(), label="Calculating")
    await d.hold(0.5)
    await d.caption("Schedule sums to the cent", step=4)
    resp = p.locator(".live-responses-table .microlight").first
    await resp.scroll_into_view_if_needed()
    await d.hold(0.4)
    bb = await resp.bounding_box()
    top = (bb["x"] - 30, bb["y"], 420, min(bb["height"], 230))
    await d.focus(top, zoom=1.5)
    await d.hold(2.4)
    await d.unfocus()
    await d.hold(0.8)

run(scene, out=str(Path(__file__).with_name("build")), title="AIOS CRM Copilot",
    subtitle="Exact pricing for real estate sales reps, served by the API", url_label="localhost:8731/docs", viewport=(900, 600))
