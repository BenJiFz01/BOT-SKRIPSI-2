from src.infra.signal_logger import SignalLogger

log = SignalLogger()
updates = [
    ('XAUUSD_M5_20260910_190508',  'WIN_TP3',   4341.55, 29),
    ('XAUUSD_M15_20260910_184512', 'WIN_TP3',   4347.00, 49),
    ('XAUUSD_M5_20260910_183006',  'WIN_TP3',   4359.60, 60),
    ('XAUUSD_H4_20260909_120005',  'CANCELLED', 0.0,     0),
    ('XAUUSD_H4_20260909_130637',  'CANCELLED', 0.0,     0),
    ('XAUUSD_H4_20260909_160953',  'CANCELLED', 0.0,     0),
    ('XAUUSD_H4_20260910_160009',  'CANCELLED', 0.0,     0),
]
for sid, outcome, price, dur in updates:
    ok = log.update_outcome(sid, outcome, price=price, duration_m=dur, notes='Manual update')
    status = 'OK' if ok else 'TIDAK DITEMUKAN'
    print(f'  [{status}] {outcome} | {sid}')
print('Selesai.')
