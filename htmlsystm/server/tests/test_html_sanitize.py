# -*- coding: utf-8 -*-
"""公告富文本净化测试。"""
import unittest

from server.html_sanitize import sanitize_announcement_content


class TestAnnouncementSanitize(unittest.TestCase):
    def test_allows_inline_bitmap_data_image(self):
        html = '<p>hello<img src="data:image/png;base64,iVBORw0KGgo=" alt="pasted"></p>'
        cleaned = sanitize_announcement_content(html)
        self.assertIn('src="data:image/png;base64,iVBORw0KGgo="', cleaned)
        self.assertIn('alt="pasted"', cleaned)

    def test_blocks_svg_data_image(self):
        html = '<img src="data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+" alt="bad">'
        cleaned = sanitize_announcement_content(html)
        self.assertNotIn('data:image/svg+xml', cleaned)
        self.assertIn('<img', cleaned)

    def test_blocks_non_image_data_url(self):
        html = '<img src="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==" alt="bad">'
        cleaned = sanitize_announcement_content(html)
        self.assertNotIn('data:text/html', cleaned)

    def test_blocks_data_url_links(self):
        html = '<a href="data:text/html;base64,PHNjcmlwdD4=">bad</a>'
        cleaned = sanitize_announcement_content(html)
        self.assertNotIn('href=', cleaned)
        self.assertIn('bad', cleaned)


if __name__ == '__main__':
    unittest.main()
