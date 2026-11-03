// HTMLの要素を取得
const form = document.getElementById("todo-form");
const input = document.getElementById("todo-input");
const list = document.getElementById("todo-list");
const count = document.getElementById("todo-count");
const search = document.getElementById("search-input");

// TODOのデータ（ブラウザに保存されたものがあれば読み込む）
// 1件のTODO = { id: 番号, text: "内容", done: 完了したか }
let todos = JSON.parse(localStorage.getItem("todos")) || [];

// データをブラウザに保存する
function save() {
  localStorage.setItem("todos", JSON.stringify(todos));
}

// 検索用に文字をそろえる（大文字→小文字、カタカナ→ひらがな）
// NFKCで半角カナ（ｶ）も全角（カ）にしてから、カタカナをひらがなに変換する
function normalize(text) {
  return text
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[ァ-ヶ]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) - 0x60));
}

// データをもとに画面を作り直す
function render() {
  list.innerHTML = "";

  // 検索ワードを含むTODOだけに絞り込む（大文字・小文字、ひらがな・カタカナは区別しない）
  const keyword = normalize(search.value.trim());
  const visibleTodos = todos.filter((t) => normalize(t.text).includes(keyword));

  visibleTodos.forEach((todo) => {
    const li = document.createElement("li");
    if (todo.done) li.classList.add("done");

    // 完了チェックボックス
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = todo.done;
    checkbox.addEventListener("change", () => {
      todo.done = !todo.done;
      save();
      render();
    });

    // TODOの文字
    const span = document.createElement("span");
    span.textContent = todo.text;

    // 削除ボタン
    const deleteBtn = document.createElement("button");
    deleteBtn.textContent = "削除";
    deleteBtn.className = "delete-btn";
    deleteBtn.addEventListener("click", () => {
      todos = todos.filter((t) => t.id !== todo.id);
      save();
      render();
    });

    li.append(checkbox, span, deleteBtn);
    list.appendChild(li);
  });

  const remaining = todos.filter((t) => !t.done).length;
  count.textContent = `残り ${remaining} 件`;
  if (keyword !== "") {
    count.textContent += `（検索結果 ${visibleTodos.length} 件）`;
  }
}

// 検索欄に入力するたびに一覧を絞り込む
search.addEventListener("input", render);

// 「追加」ボタン（またはEnter）で新しいTODOを追加
form.addEventListener("submit", (event) => {
  event.preventDefault(); // ページの再読み込みを防ぐ

  const text = input.value.trim();
  if (text === "") return; // 空なら何もしない

  todos.push({ id: Date.now(), text: text, done: false });
  input.value = "";
  save();
  render();
});

// 最初に一度画面を表示
render();
