# LogLine

로그 Text 위젯의 한 줄 — `시:분:초  레벨  출처  내용` 순서를 고정폭으로 맞춰, 언제 무엇을 근거로 무엇을 했는지 위에서 아래로 훑어 읽게 한다.

- 글꼴 `log`(Consolas 9pt), 바탕 `surface-raised`, 최신 줄이 아래. 자동 스크롤은 사용자가 맨 아래에 있을 때만.
- 레벨 열(4칸 고정): `정보`(`ink-muted`) · `확인`(`state-ok`) · `대체`(`state-unknown`) · `위험`(`state-danger`). 위험 줄만 배경 `state-danger-bg`.
- 출처 열(4칸 고정): `메모리` / `이미지` / `소리` / `타이머`.
- 내용에는 수치 근거를 넣는다: `mark2 0.74≥0.60 → F8 도주`.
- tkinter: `text.tag_configure('위험', foreground=…, background=…)` 처럼 레벨 이름을 태그로 쓴다.
