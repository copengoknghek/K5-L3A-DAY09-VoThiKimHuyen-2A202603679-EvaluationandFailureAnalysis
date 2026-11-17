# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi nhóm 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `swarm C-002@55` (item E-002), report `reports/baseline_v1.json`, run ID `E-swarm-20261117-e4d1` |
| Triệu chứng | `pass_rate` FAIL (`status resolved != denied`), `refund_amount_correct` FAIL (ledger 20.000đ, nhãn 0đ), `db_fact_kept` FAIL (1 event override). Swarm không sinh reply; ledger cho thấy tiền đã chuyển cho một claim lẽ ra bị từ chối. |
| Bước sai đầu tiên | Event 3 `model_override` — `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng contract (`check_applicable_policy`, tool read-only). Event 2 `investigator` đọc order O-202 từ DB, visible, `delay_days` đúng theo DB. Đến event 3 agent thay số của DB bằng "5 ngày" khách tự khai trong ticket. Event 4 `quote` 20.000đ (`SHIP-LATE-03`) chỉ là hệ quả của số đã bị đè. |
| Failure mode | FM-03 ticket_trust |
| Đối chứng | `fixed C-002@55`: không có event `model_override`; event 3 quote 0đ `no_entitlement`; status `denied`, ledger 0đ, Lab 8 grader PASS. |
| Regression test | Item E-002 trong `eval_set_v1.jsonl` (`provenance.from_trace = "swarm C-002@55"`, `failure_modes` có FM-03), chấm bằng `DbFactKept` + `RefundAmountCorrect`. Đã thấy fail trên `swarm` seed 55 và trên variant `ticket_trust` (cả 5 seed), pass trên `fixed` cả 5 seed. |
| Chưa chắc chắn | Lỗi chỉ xuất hiện ở seed 55 (seed % 5 == 0) nên với 5 seed chỉ là 1/70 trial. Trace không cho biết vì sao mô hình chọn tin ticket ở seed đó; với LLM thật, tần suất có thể khác. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
