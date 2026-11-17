# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt (exit 0) | **dùng** — chỉ cho giọng văn, không bao giờ cho tiền/approval |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không đạt (κ, R dưới sàn; exit 1) | **loại** |

Ma trận nhầm lẫn (FAIL là lớp dương, vì việc của judge là tìm lỗi):

| Tiêu chí | tp | fp | fn | tn | Tỉ lệ fail judge thấy | Sau Rogan-Gladen |
|---|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 0.28 | 0.30 |
| helpful | 9 | 0 | 21 | 70 | 0.09 | 0.30 |

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã với khách khiếu nại. Rubric thêm: *xưng hô phải là "LogiX – anh/chị"; "em/bạn/nha/nhé" = FAIL*. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ… rồi nha." | PASS | FAIL | Người | Cùng lỗi xưng hô ("bạn ơi"). Áp dụng luật ở case 1; thêm ví dụ âm vào few-shot của judge. |
| 3 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ nhìn "Dạ, vui lòng" mở đầu. Rubric thêm: *câu mệnh lệnh/chặn khách liên hệ = FAIL dù có kính ngữ*. |
| 4 | H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | Người | Judge phạt từ tiếng Anh, nhưng style guide CS LogiX cho phép "refund". Rubric thêm danh sách từ được phép. |
| 5 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". Rubric ghi rõ: *xin lỗi không bắt buộc khi claim được giải quyết; ngắn mà đủ ý = PASS*. |
| 6 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Người đọc nhầm ticket. Hành động: **sửa nhãn người** thành FAIL, không sửa rubric; ghi lại để đo lại κ ở lần calibrate sau. |
| 7 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | Người | Hứa hẹn ngoài kết quả hệ thống — đây là lỗi nội dung, không phải giọng văn. Không giao cho judge tone; bắt bằng code (`ReplyMatchesLedger`, FM-08). |
| 8 | HL-015 (helpful) "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." | PASS | FAIL | Người | Ledger ghi 40.000đ. Judge không thấy ledger nên không thể biết số sai. 18/21 lỗi judge helpful bỏ sót là **sai tiền**. |

## Kết luận
- **helpful bị loại.** Judge bỏ sót 21/30 reply người đánh FAIL (fn = 21, recall 0.30, κ 0.375). Trong 21 case đó, 18 là sai tiền (reply nói số khác ledger) và 3 là sai xưng hô ("Ok bạn…"). Precision 1.0 không cứu được: judge rất ít khi nói FAIL (9/100), nên tỉ lệ lỗi nó thấy (0.09) thấp hơn thực tế gần 3 lần (0.30 sau Rogan-Gladen). Nếu dùng làm gate, judge này sẽ cho qua hầu hết reply sai tiền. Lỗi tiền phải chấm bằng code đọc ledger (`ReplyMatchesLedger` / `RefundAmountCorrect`), đúng quy tắc "tiền và approval luôn chấm bằng code".
- **tone_ok dùng được** cho giọng văn, nhưng chỉ là metric theo dõi (không blocking) cho tới khi sửa rubric theo case 1–5 và calibrate lại trên nhãn mới.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai; cần nhãn người mới để có held-out thật. Một nhãn người đã sai (H-081), nên nhãn người cũng cần kiểm chéo (2 người gán, đo κ giữa người với người).
