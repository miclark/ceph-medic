from ceph_medic.checks import mons


class TestGetSecret(object):

    def setup(self):
        self.data = {
            'paths': {
                '/var/lib/ceph': {
                    'files': {
                        '/var/lib/ceph/mon/ceph-mon-0/keyring': {
                            'contents':'',
                        }
                    }
                }
            }
        }

    def set_contents(self, string, file_path=None):
        file_path = file_path or '/var/lib/ceph/mon/ceph-mon-0/keyring'
        self.data['paths']['/var/lib/ceph']['files'][file_path]['contents'] = string

    def test_get_secret(self):
        contents = """
    [mon.]
        key = AQBvaBFZAAAAABAA9VHgwCg3rWn8fMaX8KL01A==
            caps mon = "allow *"
        """
        self.set_contents(contents)
        result = mons.get_secret(self.data)
        assert result == 'AQBvaBFZAAAAABAA9VHgwCg3rWn8fMaX8KL01A=='

    def test_get_no_secret_empty_file(self):
        result = mons.get_secret(self.data)
        assert result == ''

    def test_get_no_secret_wrong_file(self):
        contents = """
    [mon.]
        caps mon = "allow *"
        """
        self.set_contents(contents)
        result = mons.get_secret(self.data)
        assert result == ''


class TestGetMonitorDirs(object):

    def test_get_monitor_dirs(self):
        result = mons.get_monitor_dirs([
            '/var/lib/ceph/mon/ceph-mon-1',
            '/var/lib/ceph/something'])

        assert result == set(['ceph-mon-1'])

    def test_cannot_get_monitor_dirs(self):
        result = mons.get_monitor_dirs([
            '/var/lib/ceph/osd/ceph-osd-1',
            '/var/lib/ceph/something'])
        assert result == set([])

    def test_get_monitor_dirs_multiple(self):
        result = mons.get_monitor_dirs([
            '/var/lib/ceph/mon/ceph-mon-1',
            '/var/lib/ceph/mon/ceph-mon-3',
            '/var/lib/ceph/mon/ceph-mon-2',
            '/var/lib/ceph/something'])

        assert result == set(['ceph-mon-1', 'ceph-mon-2', 'ceph-mon-3'])

    def test_get_monitor_dirs_nested_multiple(self):
        result = mons.get_monitor_dirs([
            '/var/lib/ceph/mon/ceph-mon-1',
            '/var/lib/ceph/mon/ceph-mon-1/nested/dir/',
            '/var/lib/ceph/mon/ceph-mon-1/other/nested',
            '/var/lib/ceph/mon/ceph-mon-2',
            '/var/lib/ceph/something'])

        assert result == set(['ceph-mon-1', 'ceph-mon-2'])
