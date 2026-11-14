# KeyRow

버프 키 설정 표의 한 행(F5–F12) — 키, 주기(초), 역할 체크박스, 주기 설명을 고정 열에 정렬해 설정 실수를 막는다.

- 열: 키(`value`, 고정폭, 가운데) · 주기 입력(`value`, 가운데) · 역할 체크박스들 · 설명(`caption`, `ink-muted`).
- 입력칸: 배경 `surface-raised`, 테두리 `line-strong`, 포커스 시 `accent` 2px. 숫자가 아니면 테두리를 `state-danger` 로 바꾸고 설명 자리에 `숫자만 입력` 을 적는다 — 저장 시점이 아니라 입력 즉시.
- 비활성(`주기 없음`, 동작 중 잠김)은 입력 글자를 `ink-muted` 로. 값은 지우지 않는다.
- 행 구분 `line` 1px, 세로 여백 `space-1`. 표 헤더 행 배경 `surface-raised`.
- 기존 `main.App` 의 `self.entry[key]`, `self.note[key]`, `self.check[(key, rid)]` 구조를 그대로 쓴다.
