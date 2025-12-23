from __future__ import annotations
from src.models.signal import Signal

def format_signal(sig: Signal) -> str:
    lines = [
        f"<b>SINYAL {sig.direction}</b>",
        f"Symbol: <b>{sig.symbol}</b>",
        f"TF Trigger: <b>{sig.tf}</b>",
        f"Candle Close: <b>{sig.close_time}</b>",
        f"Entry: <b>{sig.entry:.5f}</b>",
    ]
    if sig.sl is not None:
        lines.append(f"SL: <b>{sig.sl:.5f}</b>")
    if sig.tp is not None:
        lines.append(f"TP: <b>{sig.tp:.5f}</b>")
    if sig.rr is not None:
        lines.append(f"RR: <b>{sig.rr:.2f}</b>")
    lines.append("")
    lines.append(f"Alasan: {sig.reason}")
    lines.append("<i>Catatan: sinyal ini untuk eksekusi manual (bukan auto-trade).</i>")
    return "\n".join(lines)
