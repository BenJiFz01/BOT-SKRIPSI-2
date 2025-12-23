from __future__ import annotations

import pandas as pd

from src.models.signal import Signal
from src.engine.anytf_mta_engine import evaluate_any_tf_mta


def evaluate_signal(
    data_by_tf: dict[str, pd.DataFrame],
    symbol: str,
    trigger_tf: str,
    enabled_tfs: list[str],
    min_rr: float,
    min_confirm_votes: int,
) -> Signal | None:
    trigger_tf_u = trigger_tf.upper()
    enabled_tfs_u = [tf.upper() for tf in enabled_tfs]

    # Normalisasi key dict biar aman kalau ada yang masih lower-case
    data_by_tf_u: dict[str, pd.DataFrame] = {k.upper(): v for k, v in data_by_tf.items()}

    # Safety: pastikan trigger TF ada
    if trigger_tf_u not in data_by_tf_u:
        # kalau ada DF trigger original, simpan alasan reject di sana juga (optional)
        df_any = data_by_tf.get(trigger_tf) or data_by_tf.get(trigger_tf_u)
        if df_any is not None:
            df_any.attrs["reject_reason"] = f"MISSING_TRIGGER_TF trigger={trigger_tf_u} keys={list(data_by_tf_u.keys())}"
        return None

    return evaluate_any_tf_mta(
        data_by_tf=data_by_tf_u,
        symbol=symbol,
        trigger_tf=trigger_tf_u,
        enabled_tfs=enabled_tfs_u,
        min_rr=float(min_rr),
        min_confirm_votes=int(min_confirm_votes),
    )
