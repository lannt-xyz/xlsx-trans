"""Hộp thoại dịch thủ công: số khối không phình ra, lưu một phần rút gọn khối, nút/phím dán."""
import unittest

from tests.test_manual import SessionCase, reply_for
from xlsx_trans import manual


class TestShrinkBlock(SessionCase):
    def test_shrink_keeps_only_unsaved_items_renumbered_with_new_prompt(self):
        s = self.session()
        block = s.scan()[0]
        total = len(block.items)
        lines = reply_for(block).splitlines()
        missing_text = block.items[1].text
        lines.pop(1)
        res = s.apply_output(block, "\n".join(lines))
        self.assertEqual(res.missing, [2])
        s.shrink_block(block)
        self.assertEqual([i.id for i in block.items], [1])
        self.assertEqual(block.items[0].text, missing_text)
        self.assertIn("[1] ", block.prompt)
        self.assertNotIn(f"[{total}] ", block.prompt)
        self.assertEqual(block.tokens, s.counter(block.prompt))
        # dán lại đúng 1 mục là xong, cache đủ
        res2 = s.apply_output(block, reply_for(block))
        self.assertEqual(len(res2.saved), 1)
        self.assertEqual(block.items, [])


def _tk_ok():
    try:
        import tkinter

        tkinter.Tk().destroy()
        return True
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_tk_ok(), "cần tkinter + màn hình (xvfb-run)")
class TestManualDialog(SessionCase):
    def open(self):
        from xlsx_trans import config
        from xlsx_trans.gui import app as A
        from xlsx_trans.gui.manual_dialog import ManualDialog

        self.cfg.block_max_items = 5
        self.app = A.App(config.load_config())
        self.addCleanup(self._close)
        session = self.session()
        session.scan()
        self.dlg = ManualDialog(self.app, session)
        self.app.root.update()
        return self.dlg, session

    def _close(self):
        self.app.stop_flag = True
        self.app.bus.close()
        self.app.root.destroy()

    def put(self, text):
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(text)

    def result(self):
        return self.dlg.result_box.get("1.0", "end-1c")

    def test_paste_button_fills_result_box_not_prompt(self):
        dlg, s = self.open()
        prompt_before = dlg.prompt_box.get("1.0", "end-1c")
        self.put("[1] Hello")
        dlg.paste_result()
        self.assertEqual(self.result(), "[1] Hello")
        self.assertEqual(dlg.prompt_box.get("1.0", "end-1c"), prompt_before)
        self.put("[1] Second")  # dán lần nữa thì thay, không nối thêm
        dlg.paste_result()
        self.assertEqual(self.result(), "[1] Second")

    def test_ctrl_v_with_focus_elsewhere_goes_to_result_box(self):
        dlg, s = self.open()
        self.put("[1] X")
        self.assertEqual(dlg._ctrl_v(None), "break")
        self.assertEqual(self.result(), "[1] X")

    def test_paste_at_cursor_inserts_and_replaces_selection(self):
        dlg, s = self.open()
        dlg.result_box.insert("1.0", "AAA-BBB")
        dlg.result_box.mark_set("insert", "1.3")
        self.put("[1] X")
        self.assertEqual(dlg._paste_at_cursor(), "break")
        self.assertEqual(self.result(), "AAA[1] X-BBB")
        dlg.result_box.tag_add("sel", "1.0", "end-1c")
        self.put("NEW")
        dlg._paste_at_cursor()
        self.assertEqual(self.result(), "NEW")

    def test_uses_system_clipboard_not_stale_tk_copy(self):
        """Tk trên Windows có thể trả về prompt đã copy trước đó; dialog phải đọc qua module clipboard."""
        from unittest import mock

        dlg, s = self.open()
        dlg.copy_block()  # Tk/clipboard đang chứa prompt
        with mock.patch("xlsx_trans.gui.clipboard.get_text", return_value="[1] FROM CHAT"):
            dlg.paste_result()
            self.assertEqual(self.result(), "[1] FROM CHAT")
            dlg.result_box.delete("1.0", "end")
            dlg._paste_at_cursor()
            self.assertEqual(self.result(), "[1] FROM CHAT")

    def test_empty_clipboard_leaves_box_untouched(self):
        from unittest import mock

        dlg, s = self.open()
        dlg.result_box.insert("1.0", "keep")
        with mock.patch("xlsx_trans.gui.clipboard.get_text", return_value=None):
            dlg.paste_result()
            dlg._paste_at_cursor()
        self.assertEqual(self.result(), "keep")
        self.assertIn("Clipboard đang trống", dlg.status.get())

    def test_saving_garbage_does_not_add_a_block_or_mark_done(self):
        dlg, s = self.open()
        n = len(s.blocks)
        dlg.result_box.insert("1.0", "xin chào, đây không phải kết quả")
        dlg.save_result()
        dlg.save_result()
        self.assertEqual(len(s.blocks), n)
        self.assertEqual(dlg.state, {})
        self.assertIn("Chưa lưu được mục nào", dlg.status.get())

    def test_partial_saves_shrink_in_place_and_never_grow_block_count(self):
        dlg, s = self.open()
        n = len(s.blocks)
        block = s.blocks[0]
        lines = reply_for(block).splitlines()[:-1]  # chat thiếu mục cuối
        dlg.result_box.insert("1.0", "\n".join(lines))
        for _ in range(3):  # bấm lưu liên tiếp nhiều lần
            dlg.save_result()
        self.assertEqual(len(s.blocks), n)
        self.assertEqual(len(block.items), 1)
        self.assertEqual(dlg.pos, 0)
        self.assertNotIn(id(block), dlg.state)  # chưa xong
        # trả lời nốt mục còn lại -> khối xong, nhảy sang khối kế
        dlg.result_box.delete("1.0", "end")
        dlg.result_box.insert("1.0", reply_for(block))
        dlg.save_result()
        self.assertEqual(dlg.state[id(block)], "done")
        self.assertEqual(len(s.blocks), n)
        self.assertEqual(dlg.pos, 1 % n)

    def test_done_block_shows_saved_text_and_cannot_be_saved_twice(self):
        dlg, s = self.open()
        block = s.blocks[0]
        reply = reply_for(block)
        dlg.result_box.insert("1.0", reply)
        dlg.save_result()
        dlg.pos = 0
        dlg.refresh()
        self.assertEqual(self.result(), reply)
        self.assertIn("ĐÃ LƯU", dlg.head.get())
        before = len(s.blocks)
        dlg.save_result()
        self.assertEqual(len(s.blocks), before)
        self.assertIn("đã lưu xong", dlg.status.get())


if __name__ == "__main__":
    unittest.main()
