__author__ = 'kugandhi'

import abc

import six


@six.add_metaclass(abc.ABCMeta)
class LBaaSAbstractBulkDriver(object):

    @abc.abstractmethod
    def create_members(self, context, members):
        """
            Driver abstraction for creating members in bulk..
        :param context:
        :param members:
        :return:
        """
        pass

    @abc.abstractmethod
    def update_members(self, context, old_members, new_members):
        """
            Driver abstraction for updating members in bulk..
        :param context:
        :param old_members:
        :param new_members:
        :return:
        """
        pass

    @abc.abstractmethod
    def delete_members(self, context, members):
        """
            Driver abstraction for deleting members in bulk..
        :param context:
        :param members:
        :return:
        """
        pass
