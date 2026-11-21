# Edge cases (8): English specs

The plan wants ~8 edge cases inside the 60 (boundary values, formats, missing documents, scans). Several boundary
cases already exist; the rest are document-format variants of existing cases, so their money answer does not change.

## Already in the 60
- Room exactly at the cap: H2 v1, H12 v1. ICU exactly at the cap: D5 v1.
- Waiting-period boundaries: H4 v1 (day 25, rightly rejected) vs H4 v2 (day 38); H2 v1 (50 months vs 48).
- Admission 3 days after renewal: D4. Duplicate bill line: D8 v2. Line dated after discharge: H16 v1.

## To add (format variants of existing cases)

| # | Base case | Edge | Expected |
|---|---|---|---|
| E1 | D2 v1 | Bill uploaded as a blurred phone photo | Reads what it can; anything unreadable is "not verifiable", never guessed |
| E2 | H10 v1 | Settlement letter as a skewed, low-contrast scan | Same answer as the clean version, or explicit "could not read" |
| E3 | D6 v1 | Earlier settlement letter photographed at an angle | Same answer; if the paid amount is unreadable, says so |
| E4 | H11 v3 | Bill printed in two columns with a stamp over some amounts | Flags the obscured lines as not verifiable |
| E5 | D1 v2 | Page 2 of the bill missing (bill says "Page 1 of 2") | Notices the missing page; deductions on missing lines not verifiable |
| E6 | H1 v1 | Wrong wording uploaded: a different insurer's AS wording with this Narmada schedule | Flags the mismatch (insurer and UIN differ); asks for the right wording |
| E7 | D3 v1 | Chat only: no documents, the user types the room rate, days and the cut | Everything unverifiable; explains what to upload |
| E8 | H9 v1 | Amounts written in words only on the letter ("Rupees One Lakh Twenty-Three Thousand...") | Reads correctly; same answer |

Generation note: E1-E4 need an image/scan step (render the PDF page to an image, add blur, skew, noise or a stamp);
E5 drops a page; E6 uses another insurer's wording PDF; E8 needs an amount-in-words option.
