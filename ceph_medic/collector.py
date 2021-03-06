"""
Collect remote information on Ceph daemons, store everything in memory and make
it available as a global part of the module so that other checks can consume it
"""
from ceph_medic import metadata, remote, terminal
from ceph_medic.terminal import loader
from ceph_medic.connection import get_connection
from execnet.gateway_bootstrap import HostNotFound
import logging


logger = logging.getLogger(__name__)


def collect_paths(conn):
    """
    Gather all the interesting paths from the remote system, stat them, and
    capture contents when needed.

    Generates a tree path, using the "path of interest" as key, and appending
    the absolute paths of files in the 'files' key and directories in the
    'dirs' key. A small subset of a tree would look
    very similar to::

        {
            '/etc/ceph': {
                'dirs': {
                    '/etc/ceph/ceph.d': {...},
                },
                'files': {
                    '/etc/ceph/ceph.d/ceph.conf': {...},
                },
            }
        }

    Each file and dir in a path tree will contain a set of keys populated
    mostly by calling ``stat`` on the remote system for that absolute path, in
    addition to capturing contents when "interesting files" are dfined. For
    example, the contents of a ``ceph.conf`` file will always be captured. This
    is how that file would look like in a tree path::


        {
            '/etc/ceph/ceph.d/test.conf':
                {
                    'contents': '[osd]\nosd mkfs type = xfs\nosd mkfs options[...]    ',
                    'exception': {},
                    'group': 'ceph',
                    'n_fields': 16,
                    'n_sequence_fields': 10,
                    'n_unnamed_fields': 3,
                    'owner': 'ceph',
                    'st_atime': 1492721509.572292,
                    'st_blksize': 4096,
                    'st_blocks': 8,
                    'st_ctime': 1492721507.880156,
                    'st_dev': 64768L,
                    'st_gid': 167,
                    'st_ino': 100704475,
                    'st_mode': 33188,
                    'st_mtime': 1492721506.1060133,
                    'st_nlink': 1,
                    'st_rdev': 0,
                    'st_size': 650,
                    'st_uid': 167
                },

        }

    .. note:: ``contents`` is captured using ``file.read()`` so its value will
              be a single line with possible line breaks (if any). For reading and
              parsing that key on each line a split must be done on the line break.

    """
    path_metadata = {}
    paths = {
        "/etc/ceph": {'get_contents': True},
        "/var/lib/ceph": {
            'get_contents': True,
            'skip_files': ['activate.monmap', 'superblock'],
            'skip_dirs': ['current', 'store.db']
        },
        "/var/run/ceph": {'get_contents': False},
    }
    for p, kw in paths.items():
        # generate the tree
        tree = conn.remote_module.path_tree(
            p,
            kw.get('skip_dirs'),
            kw.get('skip_files'),
            kw.get('get_contents')
        )

        files = {}
        dirs = {}

        for i in tree['files']:
            files[i] = conn.remote_module.stat_path(i, None, None, kw.get('get_contents'))
        for i in tree['dirs']:
            dirs[i] = conn.remote_module.stat_path(i, None, None, False)

            # actual root path
            dirs[p] = conn.remote_module.stat_path(i, None, None, False)

        # Now slap the files and dirs back to the path_metadata for the current node
        path_metadata[p] = {'dirs': dirs, 'files': files}
    return path_metadata


def collect():
    """
    The main collecting entrypoint. This function will call all the pieces
    needed to build the complete metadata set of a remote system so that checks
    can consume and verify that data.

    After collection is done, the full contents of the metadata are available
    at ``ceph_medic.metadata``
    """
    cluster_nodes = metadata['nodes']
    loader.write('collecting remote node information')
    total_nodes = 0
    failed_nodes = 0
    for node_type, nodes in cluster_nodes.items():
        for node in nodes:
            total_nodes += 1
            hostname = node['host']
            loader.write('Host: %-20s  connection: [%-20s]' % (hostname, terminal.yellow('connecting')))
            # TODO: make sure that the hostname is resolvable, trying to
            # debug SSH issues with execnet is pretty hard/impossible, use
            # util.net.host_is_resolvable
            try:
                logger.debug('attempting connection to host: %s', node['host'])
                conn = get_connection(node['host'])
                loader.write('Host: %-20s  connection: [%-20s]' % (hostname, terminal.green('connected')))
                loader.write('\n')
            except HostNotFound:
                logger.exception('connection failed')
                loader.write('Host: %-20s  connection: [%-20s]' % (hostname, terminal.red('failed')))
                loader.write('\n')
                failed_nodes += 1
                continue

            # "import" the remote functions so that remote calls using the
            # functions can be executed
            conn.import_module(remote.functions)

            node_metadata = {'ceph': {}}

            # collect paths and files first
            loader.write('Host: %-*s  collecting: [%s]' % (20, hostname, terminal.yellow('paths')))
            node_metadata['paths'] = collect_paths(conn)
            loader.write('Host: %-*s  collecting: [%s]' % (20, hostname, terminal.green('paths')))

            # TODO: collect network information, passing all the cluster_nodes
            # so that it can check for inter-node connectivity
            loader.write('Host: %-*s  collecting: [%s]' % (20, hostname, terminal.yellow('network')))
            node_metadata['network'] = collect_network(cluster_nodes)
            loader.write('Host: %-*s  collecting: [%s]' % (20, hostname, terminal.green('network')))

            # TODO: collect device information
            loader.write('Host: %-*s  collecting: [%s]' % (20, hostname, terminal.yellow('devices')))
            node_metadata['devices'] = collect_devices()
            loader.write('Host: %-*s  collecting: [%s]' % (20, hostname, terminal.green('paths')))

            # collect ceph information
            node_metadata['ceph']['version'] = remote.commands.ceph_version(conn)
            loader.write('Host: %-*s  collecting: [%s]' % (20, hostname, terminal.green('paths')))
            node_metadata['ceph']['installed'] = remote.commands.ceph_is_installed(conn)
            loader.write('Host: %-*s  collecting: [%s]' % (20, hostname, terminal.green('paths')))
            # send the full node metadata for global scope so that the checks
            # can consume this
            metadata[node_type][node['host']] = node_metadata
            conn.exit()
    if failed_nodes == total_nodes:
        loader.write(terminal.red('Collection failed!') + ' ' *70 + '\n')
        raise RuntimeError('All nodes failed to connect. Cannot run any checks')
    else:
        loader.write('Collection completed!' + ' ' *70 + '\n')


# Network
#
def collect_network(cluster_nodes):
    """
    Collect node-specific information, but also try to check connectivity to
    other hosts that are passed in as ``cluster_nodes``
    """
    return {}


# Devices
#
def collect_devices():
    """
    Get all the device information from the current node
    """
    return {}


# Ceph
#
# XXX there are lots of pieces to collect about ceph, like repository
# information, where did the ceph package came from, versions, etc... we can't
# pile everything on one function
def collect_ceph():
    pass
