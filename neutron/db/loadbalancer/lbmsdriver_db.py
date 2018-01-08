# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2014 OpenStack Foundation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#


from neutron.db import db_base_plugin_v2 as base_db
import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.orm import exc

from neutron.db import model_base
from neutron.db import models_v2
from neutron.common import exceptions as qexception
from neutron.db.loadbalancer import loadbalancer_db as lb_db
from neutron.openstack.common import log as logging
from neutron.openstack.common import timeutils
from neutron.openstack.common import uuidutils

LOG = logging.getLogger(__name__)

class LBMSDriverJob(model_base.BASEV2, lb_db.HasTimeStamp, models_v2.HasId):
    """Represents a lbms driver job
    """
    __tablename__ = 'lbmsdriver_job'
    action = sa.Column(sa.String(255))
    data = sa.Column(sa.Text(20480))


class LBMSDriverJobNotFound(qexception.NotFound):
    message = _("LBMSDriver Job %(job_id)s does not exist")

class LBMSDriverDbMixin(base_db.CommonDbMixin):

    def get_lbmsdriver_jobs(self, context, filters=None, fields=None):
        return self._get_collection(context, LBMSDriverJob,
                                    self._make_lbmsdriver_job_dct,
                                    filters=filters, fields=fields)


    def create_job(self, context, action, data):
        with context.session.begin(subtransactions=True):
            lbmsdriverjob_db = LBMSDriverJob(
                id=uuidutils.generate_uuid(),
                action=action,
                data=data,
                created_at=timeutils.utcnow()
            )
            context.session.add(lbmsdriverjob_db)
            return self._make_lbmsdriver_job_dct(lbmsdriverjob_db)

    def delete_job(self, context, job_id):
        try:
            lbmsdriverjob_db = self._get_by_id(context, LBMSDriverJob, job_id)
            context.session.delete(lbmsdriverjob_db)
            context.session.flush()
        except Exception as e:
            # There is chance that job will deleted, if there are competing threads running
            # on the same job. This only happens in the use case where first time job
            # execution took more time and the pending jobs retry also kicked in. There is
            # no side effects to this issue other than delete job will be called twice
            LOG.error("Unable to delete the job id %s" % job_id)

    def has_lock(self, context, host):
        with context.session.begin(subtransactions=True):
            try:
                lock_record = context.session.query(
                    LBMSDriverJob).filter(LBMSDriverJob.id==1).one()
                if (lock_record['action'] == host):
                    return True
                else:
                    return False
            except Exception, e:
                return False

    # Create the lock record if it doesn't exist or update it
    def create_or_update_lock_record(self, context, host, wait_time_to_get_lock):
        with context.session.begin(subtransactions=True):
            try:
                lock_record = self._get_by_id(context, LBMSDriverJob, 1)
                # if host matches, this instance has the lock, then just update the lock
                if (lock_record['action'] == host):
                    lock_record['updated_at'] = timeutils.utcnow()

                # if no instance updated the lock until the wait time, take the lock
                if (timeutils.is_older_than(lock_record['updated_at'],
                                            wait_time_to_get_lock)):
                    lock_record['updated_at'] = timeutils.utcnow()
                    lock_record['action'] = host


            except exc.NoResultFound:
                lock_record = LBMSDriverJob(
                    id=1,
                    action=host,
                    data="lock record",
                    created_at=timeutils.utcnow(),
                    updated_at=timeutils.utcnow()
                )
                context.session.add(lock_record)


    def _make_lbmsdriver_job_dct(self, lbmddriverjob, fields=None):
        res = {'id': lbmddriverjob['id'],
               'action': lbmddriverjob['action'],
               'data': lbmddriverjob['data'],
               'created_at' : lbmddriverjob['created_at'],
               'updated_at': lbmddriverjob['updated_at']}

        return res

