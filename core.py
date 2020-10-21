import shlex
import atexit
import weakref
import subprocess
import sys
from functools import partial
from threading import Thread
import config

try:
    import queue
except ImportError:
    import Queue as queue

import mtypes, misc

__all__ = ['Player', 'Step']


def _quit(player):
    try:
        player.quit()
    except ReferenceError:
        pass


class Step(object):

    def __init__(self, value=0, direction=0):
        super(Step, self).__init__()
        if not isinstance(value, mtypes.FloatType.type):
            raise TypeError('expected float or int for value')
        if not isinstance(direction, mtypes.IntegerType.type):
            raise TypeError('expected int for direction')
        self._val = mtypes.FloatType.adapt(value)
        self._dir = mtypes.IntegerType.adapt(direction)


class Player(object):
    _base_args = ('-slave', '-idle', '-really-quiet', '-msglevel', 'global=4',
                  '-input', 'nodefault-bindings', '-fs')
    cmd_prefix = misc.CmdPrefix.PAUSING_KEEP_FORCE
    exec_path = config.exec_path
    version = None

    def __init__(self, args=(), stdout=subprocess.PIPE, stderr=None, autospawn=True):
        super(Player, self).__init__()
        self.args = args
        self._stdout = _StdoutWrapper(handle=stdout)
        self._stderr = _StderrWrapper(handle=stderr)
        self._proc = None
        atexit.register(_quit, weakref.proxy(self))

        if autospawn:
            self.spawn()

    def __del__(self):
        if self.is_alive():
            self.quit()

    def __repr__(self):
        if self.is_alive():
            status = 'with pid = {0}'.format(self._proc.pid)
        else:
            status = 'not running'
        return '<{0} {1}>'.format(self.__class__.__name__, status)

    @property
    def stdout(self):
        return self._stdout

    @property
    def stderr(self):
        return self._stderr

    @property
    def args(self):
        return self._args[len(self._base_args):]

    @args.setter
    def args(self, args):
        try:
            args = shlex.split(args)
        except AttributeError:
            args = map(str, args)
        self._args = self._base_args + tuple(args)

    def _propget(self, pname, ptype):
        res = self._run_command('get_property', pname)
        if res is not None:
            return ptype.convert(res)

    def _propset(self, value, pname, ptype, pmin, pmax):
        if not isinstance(value, Step):
            if not isinstance(value, ptype.type):
                raise TypeError('expected {0}'.format(ptype.name))
            if pmin is not None and value < pmin:
                raise ValueError('value must be at least {0}'.format(pmin))
            if pmax is not None and value > pmax:
                raise ValueError('value must be at most {0}'.format(pmax))
            self._run_command('set_property', pname, ptype.adapt(value))
        else:
            self._run_command('step_property', pname, value._val, value._dir)

    @staticmethod
    def _gen_propdoc(ptype, pmin, pmax, propset):
        doc = ['type: {0}'.format(ptype.name)]
        if propset is not None:
            if pmin is not None:
                doc.append('min: {0}'.format(pmin))
            if pmax is not None:
                doc.append('max: {0}'.format(pmax))
        else:
            doc.append('(read-only)')
        return '\n'.join(doc)

    @classmethod
    def _generate_properties(cls):
        read_only = ['length', 'pause', 'stream_end', 'stream_length',
                     'stream_start', 'stream_time_pos']
        rename = {'pause': 'paused'}
        proc = subprocess.Popen([cls.exec_path, '-list-properties'],
                                bufsize=-1, stdout=subprocess.PIPE)

        try:
            cls.version = proc.stdout.readline().decode('utf-8', 'ignore').split()[1]
        except IndexError:
            pass
        for line in proc.stdout:
            line = line.decode('utf-8', 'ignore').split()
            if not line or not line[0].islower():
                continue
            try:
                pname, ptype, pmin, pmax = line
            except ValueError:
                pname, ptype, ptype2, pmin, pmax = line
                ptype += ' ' + ptype2
            ptype = mtypes.type_map[ptype]
            pmin = ptype.convert(pmin) if pmin != 'No' else None
            pmax = ptype.convert(pmax) if pmax != 'No' else None
            propget = partial(cls._propget, pname=pname, ptype=ptype)
            if (pmin is None and pmax is None and pname != 'sub_delay') or \
                    pname in read_only:
                propset = None
            else:
                if ptype is mtypes.FlagType:
                    pmin = pmax = None
                propset = partial(cls._propset, pname=pname, ptype=ptype,
                                  pmin=pmin, pmax=pmax)
            propdoc = cls._gen_propdoc(ptype, pmin, pmax, propset)
            prop = property(propget, propset, doc=propdoc)
            if pname in rename:
                pname = rename[pname]
            assert not hasattr(cls, pname), "name conflict for '{0}'".format(pname)
            setattr(cls, pname, prop)

    @staticmethod
    def _process_args(req, types, *args):
        args = list(args[:req]) + [x for x in args[req:] if x is not None]
        for i, arg in enumerate(args):
            if not isinstance(arg, types[i].type):
                msg = 'expected {0} for argument {1}'.format(types[i].name, i + 1)
                raise TypeError(msg)
            args[i] = types[i].adapt(arg)
        return tuple(args)

    @staticmethod
    def _gen_method_func(name, args):
        sig = []
        types = []
        required = 0
        for i, arg in enumerate(args):
            if not arg.startswith('['):
                optional = ''
                required += 1
            else:
                arg = arg.strip('[]')
                optional = '=None'
            t = mtypes.type_map[arg]
            sig.append('{0}{1}{2}'.format(t.name, i, optional))
            types.append('mtypes.{0},'.format(t.__name__))
        sig = ','.join(sig)
        params = sig.replace('=None', '')
        types = ''.join(types)
        args = ', '.join(args)
        code = '''
        def {name}(self, {sig}):
            """{name}({args})"""
            args = self._process_args({required}, ({types}), {params})
            return self._run_command('{name}', *args)
        '''.format(**locals())
        local = {}
        exec(code.strip(), globals(), local)
        return local[name]

    @classmethod
    def _generate_methods(cls):
        truncated = {'osd_show_property_te': 'osd_show_property_text'}
        proc = subprocess.Popen([cls.exec_path, '-input', 'cmdlist'],
                                bufsize=-1, stdout=subprocess.PIPE)
        for line in proc.stdout:
            line = line.decode('utf-8', 'ignore')
            if line.startswith("MPlayer"):
                continue
            args = line.split()
            if not args:
                continue
            name = args.pop(0)
            if hasattr(cls, name):
                continue
            if name.startswith('get_') or name.endswith('_property'):
                continue
            if name in truncated:
                name = truncated[name]
            func = cls._gen_method_func(name, args)
            setattr(cls, name, func)

    @classmethod
    def introspect(cls):
        if cls.version is None:
            cls._generate_properties()
            cls._generate_methods()

    def spawn(self):
        if self.is_alive():
            return
        args = [self.exec_path]
        args.extend(self._args)
        self._proc = subprocess.Popen(args, stdin=subprocess.PIPE,
                                      stdout=self._stdout._handle, stderr=self._stderr._handle,
                                      close_fds=(sys.platform != 'win32'))

        if self._proc.stdout is not None:
            self._stdout._attach(self._proc.stdout)
        if self._proc.stderr is not None:
            self._stderr._attach(self._proc.stderr)

    def quit(self, retcode=0):
        if not isinstance(retcode, mtypes.IntegerType.type):
            raise TypeError('expected int for retcode')
        if not self.is_alive():
            return
        if self._proc.stdout is not None:
            self._stdout._detach()
        if self._proc.stderr is not None:
            self._stderr._detach()
        self._run_command('quit', mtypes.IntegerType.adapt(retcode))
        return self._proc.wait()

    def is_alive(self):
        if self._proc is not None:
            return (self._proc.poll() is None)
        else:
            return False

    def _run_command(self, name, *args):
        if not self.is_alive():
            return
        cmd = [self.cmd_prefix, name]
        cmd.extend(args)
        cmd.append('\n')
        if name in ['quit', 'pause', 'stop', 'loadfile', 'loadlist']:
            cmd.pop(0)
        cmd = ' '.join(cmd)
        try:
            self._proc.stdin.write(cmd)
        except (TypeError, UnicodeEncodeError):
            self._proc.stdin.write(cmd.encode('utf-8', 'ignore'))
        self._proc.stdin.flush()
        if name == 'get_property' and self._proc.stdout is not None:
            key = 'ANS_{0}='.format(args[0])
            while True:
                try:
                    res = self._stdout._answers.get(timeout=1.0)
                except queue.Empty:
                    return
                if res.startswith(key):
                    break
                if res.startswith('ANS_ERROR='):
                    return
            ans = res.partition('=')[2].strip('\'"')
            if ans == '(null)':
                ans = None
            return ans


class _StderrWrapper(misc._StderrWrapper):

    def _attach(self, source):
        super(_StderrWrapper, self)._attach(source)
        t = Thread(target=self._thread_func)
        t.daemon = True
        t.start()

    def _thread_func(self):
        while self._source is not None:
            self._process_output()


class _StdoutWrapper(_StderrWrapper, misc._StdoutWrapper):
    pass


try:
    Player.introspect()
except OSError:
    pass

if __name__ == '__main__':
    import sys


    def log(data):
        print('LOG: {0}'.format(data))


    def error(data):
        print('ERROR: {0}'.format(data))


    player = Player(sys.argv[1:], stderr=subprocess.PIPE)
    player.stdout.connect(log)
    player.stderr.connect(error)

    input()
