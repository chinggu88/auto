# StatusBadge

판정 하나를 색 사각형과 텍스트 라벨로 보여주는 배지 — tri-state(`True`/`False`/`None`)와 위험을 정확히 네 가지로만 표시한다.

| 상태 | 라벨 | 글자/사각형 | 배경 |
|---|---|---|---|
| `True` | 확인 | `state-ok` | `state-ok-bg` |
| `False` | 아님 | `state-idle` | `surface-raised` |
| `None` | 판단불가 | `state-unknown` | `state-unknown-bg` |
| 위험 | 위험 | `state-danger` | `state-danger-bg` |

- 라벨은 절대 생략하지 않는다. 색만 있는 배지는 금지.
- 사용처가 제공할 것: 상태 값, 그리고 필요하면 뒤에 붙는 짧은 근거(`· 메모리`).
- 글자 `caption` 굵게(700), 안쪽 여백 `space-1`/`space-2`, 모서리 `radius-sm`.
- tkinter: `tk.Label(bg=…, fg=…, font=('Malgun Gothic', 9, 'bold'), padx=6, pady=2)` 앞에 8×8 `tk.Frame`.
