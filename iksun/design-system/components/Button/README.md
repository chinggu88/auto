# Button

명령 버튼 — 창 안에 주 버튼(`accent`)은 시작/정지 하나뿐이고, 나머지(설정 저장·불러오기·기본값)는 모두 보조 버튼이다.

- 주 버튼: 배경 `accent`, 글자 `accent-ink`, `section` 굵기, 높이 36px, 창 너비 가득. 동작 중에는 배경 `surface-raised`, 테두리 `line-strong`, 문구 `동작 중  (tab = 정지)` — 정지 방법이 항상 보이도록 문구를 바꾸되 숨기지 않는다.
- 보조 버튼: 배경 `surface`, 테두리 `line-strong`, 글자 `ink`, 높이 28px.
- 비활성: 글자 `ink-muted`, 테두리 `line`. 클릭은 무시.
- 포커스: `accent` 2px 링. 모서리 `radius-md`.
- 상태 색(`state-*`)을 버튼 배경에 쓰지 않는다. 버튼은 행동, 상태 색은 판정이다.
