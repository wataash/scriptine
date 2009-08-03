import sys
import types
import inspect
import re
import optparse
from collections import defaultdict
from textwrap import wrap

from scriptine import misc

_global_options = None

def global_options():
    global _global_options
    return _global_options

def parse_and_run_function(function, args=None, command_name=None,
        global_options=None, add_dry_run_option=True):
    #TODO refactor me, I'm too long
    if args is None:
        args = sys.argv
    
    required_args, optional_args = inspect_args(function)
    
    func_doc = function.__doc__ or ''
    params_doc = parse_rst_params(func_doc)
    
    usage = 'usage: %prog '
    if command_name is not None:
        usage += command_name + ' '
    usage += '[options] ' + ' '.join(required_args)
    
    if func_doc:
        usage += '\n\n' + '\n'.join(wrap(func_doc.strip().split('\n')[0], 60))
    
    if set(required_args).intersection(params_doc.keys()):
        usage += '\n\nRequired arguments:'
        for arg in required_args:
            usage += '\n%s' % arg
            if arg in params_doc:
                usage += ': %s' % params_doc[arg]
        
    add_help_option = True
    if getattr(function, 'no_help', False):
        add_help_option = False
    
    fetch_all = None
    if hasattr(function, 'fetch_all'):
        fetch_all = function.fetch_all
        optional_args = [(arg, default) for arg, default in optional_args
            if arg != fetch_all]
    
    parser = optparse.OptionParser
    if getattr(function, 'non_strict', False):
        parser = NonStrictOptionParser
    
    parser = parser(usage, add_help_option=add_help_option)
    
    for arg_name, default in optional_args:
        options = {}
        if isinstance(default, bool):
            if default:
                options =  {'action': 'store_false'}
            else: 
                options =  {'action': 'store_true'}
        elif isinstance(default, int):
            options =  {'type': 'int'}
        elif isinstance(default, float):
            options =  {'type': 'float'}
        parser.add_option('--' + arg_name.replace('_', '-'),
                          help=params_doc.get(arg_name, None),
                          dest=arg_name, default=default, metavar=default, **options)
    
    if add_dry_run_option:
        parser.add_option('--dry-run', '-n', dest='dry_run', default=False,
            action='store_true', help='don\'t actually do anything')
    
    if global_options:
        if '--help' in args or '-h' in args:
            group = optparse.OptionGroup(parser, 'Global options')
            group.add_options(global_options)
            parser.add_option_group(group)
        else:
            args = parse_global_options(args, global_options)
    
    (options, args) = parser.parse_args(args)
    
    if add_dry_run_option and options.dry_run:
        misc.options.dry = True
    
    args = args[1:]
    if len(args) < len(required_args):
        parser.error('number of arguments does not match')
    kw = {}
    for arg_name, _default in optional_args:
        kw[arg_name] = getattr(options, arg_name)
    
    if fetch_all:
        kw[fetch_all] = args[len(required_args):]
    return function(*args[:len(required_args)], **kw)

def no_help(cmd):
    cmd.no_help = True
    return cmd

def non_strict(cmd):
    cmd.non_strict = True
    return cmd

def fetch_all(arg_name):
    def _fetch_all(cmd):
        cmd.fetch_all = arg_name
        return cmd
    return _fetch_all

def group(name):
    def _group(cmd):
        cmd.group = name
        return cmd
    return _group

def parse_global_options(args, global_options):
    parser = NonStrictOptionParser(add_help_option=False)
    parser.add_options(global_options)
    (options, args) = parser.parse_args(args)
    global _global_options
    _global_options = options
    return args

class NonStrictOptionParser(optparse.OptionParser):
    def _process_args(self, largs, rargs, values):
        while rargs:
            arg = rargs[0]
            # We handle bare "--" explicitly, and bare "-" is handled by the
            # standard arg handler since the short arg case ensures that the
            # len of the opt string is greater than 1.
            try:
                if arg == "--":
                    del rargs[0]
                    return
                elif arg[0:2] == "--":
                    # process a single long option (possibly with value(s))
                    self._process_long_opt(rargs, values)
                elif arg[:1] == "-" and len(arg) > 1:
                    # process a cluster of short options (possibly with
                    # value(s) for the last one only)
                    self._process_short_opts(rargs, values)
                elif self.allow_interspersed_args:
                    largs.append(arg)
                    del rargs[0]
                else:
                    return
            except optparse.BadOptionError:
                largs.append(arg)
    
def inspect_args(function):
    (args, _varargs, _varkw, defaults) = inspect.getargspec(function)
    
    optional_args = []
    if defaults is not None:
        for default in defaults[::-1]:
            optional_args.append((args.pop(), default))
        optional_args.reverse()
    return args, optional_args

def run(namespace=None, args=None, global_options=None,
        add_dry_run_option=True, command_suffix='_command'):
    """
    Parse and run commands.
    
    Will search ``namespace`` for functions that end with ``command_suffix``.
    
    :param namespace: the namespace/module to search for commands
    :param args: the arguments for the command parser. defaults to
        :data:`sys.argv`
    :param command_suffix: function name suffix that indicates that a
        function is a command.
    """
    if namespace is None:
        namespace = inspect.currentframe().f_back.f_globals
    elif type(namespace) is types.ModuleType:
        namespace = namespace.__dict__
    
    if args is None:
        args = sys.argv
    
    if len(args) < 2 or args[1] in ('-h', '--help'):
        print_help(namespace, command_suffix, global_options)
        return
    
    command_name = args.pop(1).replace('-', '_')
    function = namespace[command_name + command_suffix]
    parse_and_run_function(function, args, command_name, global_options,
        add_dry_run_option=add_dry_run_option)

def print_help(namespace, command_suffix, global_options):
    group_commands = defaultdict(list)
    for func_name, func in namespace.iteritems():
        if func_name.endswith(command_suffix):
            func = namespace[func_name]
            group = getattr(func, 'group', None)
            command_name = func_name[:-len(command_suffix)].replace('_', '-')
            group_commands[group].append((command_name, func.__doc__))
    
    if not group_commands:
        print 'no commands found in', sys.argv[0]
        return
    
    usage = 'usage: %prog command [options]'
    parser = optparse.OptionParser(usage)
    if global_options:
        parser.add_options(global_options)
    parser.print_help()
    
    default_commands = group_commands.pop(None, None)
    if default_commands:
        print_commands(None, default_commands)
    for group_name, commands in group_commands.iteritems():
        print_commands(group_name, commands)

def print_commands(group_name, commands):
    if group_name:
        print '\n%s commands:' % group_name.title()
    else:
        print '\nCommands:'
    cmd_len = max(len(cmd) for cmd, _ in commands)
    for cmd, doc in commands:
        if doc is not None:
            doc = doc.strip().split('\n')[0]
        else:
            doc = ''
        print ('  %-' + str(cmd_len) + 's  %s') % (cmd, doc)

def parse_rst_params(doc):
    """
    Parse a reStructuredText docstring and return a dictionary
    with parameter names and descriptions. 
    
    >>> doc = '''
    ... :param foo: foo parameter
    ...     foo parameter
    ... 
    ...  :param bar: bar parameter
    ...  :param baz: baz parameter
    ...         baz parameter
    ...     baz parameter
    ...  Some text.
    ... '''
    >>> params = parse_rst_params(doc)
    >>> params['foo']
    'foo parameter foo parameter'
    >>> params['bar']
    'bar parameter'
    >>> params['baz']
    'baz parameter baz parameter baz parameter'
    """
    param_re = re.compile(r"""^([ \t]*):param\ 
                              (?P<param>\w+):\ 
                              (?P<body>.*\n(\1[ \t]+\w.*\n)*)""",
                          re.MULTILINE|re.VERBOSE)
    params = {}
    for match in param_re.finditer(doc):
        parts = match.groupdict()
        body_lines = parts['body'].strip().split('\n')
        params[parts['param']] = ' '.join(s.strip() for s in body_lines)
    
    return params