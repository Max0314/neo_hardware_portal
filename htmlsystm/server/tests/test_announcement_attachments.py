import base64
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server.announcement_manager import AnnouncementManager


def upload(name, content):
    return {
        'name': name,
        'size': len(content),
        'type': 'text/plain',
        'data': base64.b64encode(content).decode('ascii'),
    }


class AnnouncementAttachmentUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.board_patch = patch.object(
            AnnouncementManager,
            '_get_all_board_ids',
            return_value={'hardware'},
        )
        self.mirror_patch = patch(
            'server.announcement_manager._announcement_mirror',
            return_value=SimpleNamespace(store=None),
        )
        # Existing version directory names contain ':' and are Linux-only.  This
        # suite isolates attachment state transitions on the Windows dev host.
        self.version_patch = patch.object(
            AnnouncementManager,
            '_save_version',
            return_value=True,
        )
        self.board_patch.start()
        self.mirror_patch.start()
        self.version_patch.start()
        self.manager = AnnouncementManager(base_dir=self.temp_dir.name)

    def tearDown(self):
        self.version_patch.stop()
        self.mirror_patch.stop()
        self.board_patch.stop()
        self.temp_dir.cleanup()

    def create(self, attachments, status='approved'):
        announcement_id, message = self.manager.create_announcement(
            board_id='hardware',
            title='附件测试',
            content='<p>正文</p>',
            author='tester',
            status=status,
            attachments=attachments,
            user_id='tester' if status == 'draft' else None,
        )
        self.assertIsNotNone(announcement_id, message)
        return announcement_id

    def attachment_bytes(self, announcement_id, name, view):
        metadata = self.manager.get_announcement_for_download(
            announcement_id,
            view=view,
        )
        path = self.manager.get_attachment(
            announcement_id,
            name,
            metadata=metadata,
            view=view,
        )
        self.assertIsNotNone(path)
        with open(path, 'rb') as file:
            return file.read()

    def test_approved_edit_replaces_same_name_only_in_pending_until_approval(self):
        announcement_id = self.create([upload('guide.txt', b'old')])

        success, message = self.manager.update_announcement(
            announcement_id,
            editor='editor',
            title='附件测试新版',
            status='pending',
            attachments=[upload('guide.txt', b'new')],
        )

        self.assertTrue(success, message)
        self.assertEqual(
            self.attachment_bytes(announcement_id, 'guide.txt', 'published'),
            b'old',
        )
        self.assertEqual(
            self.attachment_bytes(announcement_id, 'guide.txt', 'pending'),
            b'new',
        )

        success, message = self.manager.approve_announcement(
            announcement_id,
            approve=True,
            approver='reviewer',
        )
        self.assertTrue(success, message)
        self.assertEqual(
            self.attachment_bytes(announcement_id, 'guide.txt', 'published'),
            b'new',
        )
        self.assertIsNone(self.manager.get_pending_announcement(announcement_id))

    def test_approved_edit_adds_and_deletes_attachments(self):
        announcement_id = self.create([
            upload('keep.txt', b'keep'),
            upload('remove.txt', b'remove'),
        ])
        keep_ref = {'name': 'keep.txt', 'size': 4, 'type': 'text/plain'}

        success, message = self.manager.update_announcement(
            announcement_id,
            editor='editor',
            attachments=[keep_ref, upload('added.txt', b'added')],
        )

        self.assertTrue(success, message)
        pending = self.manager.get_pending_announcement(announcement_id)
        self.assertEqual(
            [attachment['name'] for attachment in pending['attachments']],
            ['keep.txt', 'added.txt'],
        )
        pending_dir = os.path.join(
            self.manager.base_dir,
            self.manager.temp_dir,
            announcement_id,
            'attachments',
        )
        self.assertEqual(set(os.listdir(pending_dir)), {'keep.txt', 'added.txt'})

        published = self.manager.get_published_announcement(announcement_id)
        self.assertEqual(
            {attachment['name'] for attachment in published['attachments']},
            {'keep.txt', 'remove.txt'},
        )

    def test_deletion_only_update_removes_all_draft_attachments(self):
        announcement_id = self.create([
            upload('one.txt', b'one'),
            upload('two.txt', b'two'),
        ], status='draft')

        success, message = self.manager.update_announcement(
            announcement_id,
            editor='tester',
            attachments=[],
        )

        self.assertTrue(success, message)
        draft = self.manager.get_pending_announcement(announcement_id)
        self.assertEqual(draft['attachments'], [])
        attachment_dir = os.path.join(
            self.manager.base_dir,
            self.manager.temp_dir,
            'tester',
            announcement_id,
            'attachments',
        )
        self.assertEqual(os.listdir(attachment_dir), [])

    def test_rejected_edit_leaves_published_attachment_unchanged(self):
        announcement_id = self.create([upload('guide.txt', b'old')])
        success, message = self.manager.update_announcement(
            announcement_id,
            editor='editor',
            attachments=[upload('guide.txt', b'new')],
        )
        self.assertTrue(success, message)

        success, message = self.manager.approve_announcement(
            announcement_id,
            approve=False,
            approver='reviewer',
        )

        self.assertTrue(success, message)
        self.assertEqual(
            self.attachment_bytes(announcement_id, 'guide.txt', 'published'),
            b'old',
        )
        self.assertIsNone(self.manager.get_pending_announcement(announcement_id))


if __name__ == '__main__':
    unittest.main()
