
class MPlayerType(object):

    name = None
    type = None
    convert = None
    adapt = staticmethod(repr)


class FlagType(MPlayerType):

    name = 'bool'
    type = bool

    @staticmethod
    def convert(res):
        return (res in ['yes', '1'])

    @staticmethod
    def adapt(obj):
        return MPlayerType.adapt(int(obj))


class IntegerType(MPlayerType):

    name = 'int'
    type = int
    convert = staticmethod(int)


class FloatType(MPlayerType):

    name = 'float'
    type = (float, int)
    convert = staticmethod(float)


class StringType(MPlayerType):

    name = 'string'
    try:
        type = basestring
    except NameError:
        type = str

    @staticmethod
    def convert(res):
        return res

    try:
        unicode
    except NameError:
        pass
    else:
        @staticmethod
        def adapt(obj):
            return obj.replace('\\', r'\\').replace(' ', r'\ ')


class StringListType(MPlayerType):

    name = 'dict'

    @staticmethod
    def convert(res):
        res = res.split(',')
        return dict(zip(res[::2], res[1::2]))


type_map = {
    'Flag': FlagType, 'Integer': IntegerType, 'Position': IntegerType,
    'Float': FloatType, 'Time': FloatType, 'String': StringType,
    'String list': StringListType
}
