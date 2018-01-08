# Copyright 2016 OpenStack Foundation
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

"""f5-agent active active support

Revision ID: bd1bcb82f8a
Revises: 3ccc7802d9db
Create Date: 2016-01-11 15:23:02.145459

"""

# revision identifiers, used by Alembic.
revision = 'bd1bcb82f8a'
down_revision = 'juno'

from alembic import op
from sqlalchemy.sql import text

LIKE_CLAUSE_PREFIX_AND_SUFFIX = '%'
# pulls the agent id and lb device host name for the new upgraded agent.
SQL_STATEMENT_TO_FIND_AGENTS = "SELECT a.id, SUBSTRING(configurations, LOCATE('{\"icontrol_endpoints\": " \
                "{\"', configurations) + LENGTH('{\"icontrol_endpoints\": {\"'), " \
                "(LOCATE('\"', configurations, LOCATE('{\"icontrol_endpoints\": {\"', configurations) " \
                "+ LENGTH('{\"icontrol_endpoints\": {\"'))) - (LOCATE('{\"icontrol_endpoints\": {\"', configurations) + " \
                "LENGTH('{\"icontrol_endpoints\": {\"'))) as 'device_host'" \
                "FROM agents a " \
                "WHERE a.agent_type =  'Loadbalancer agent' " \
                "AND a.binary = :binary_type"


# pulls existing old agents.
SQL_STATEMENT_TO_BACKUP_OLD_AGENTS = "SELECT id "\
                                     "FROM agents a "\
                                     "WHERE a.agent_type =  'Loadbalancer agent' "\
                                     "AND a.binary = :binary_type "\
                                     "AND a.configurations LIKE :device"

UPDATE_STATEMENT_TO_MIGRATE_POOL_AGENT_BINDING = 'UPDATE poolloadbalanceragentbindings SET agent_id = :new_agent_id ' \
                                                 'WHERE agent_id = :old_agent_id '



def _migrate_agent_pool_binding(new_id, device, binary_type):
    conn = op.get_bind()

    #get the old agent for the same device
    device_var_val = LIKE_CLAUSE_PREFIX_AND_SUFFIX + device + LIKE_CLAUSE_PREFIX_AND_SUFFIX
    rs = conn.execute(text(SQL_STATEMENT_TO_BACKUP_OLD_AGENTS), device=device_var_val, binary_type=binary_type)
    result = rs.fetchall()
    for row in result:
        (old_id) = (row[0])
        print 'migrating agent pool binding from agent %s to agent %s' %(old_id, new_id)

        # updating the pool agent bindings
        conn.execute(text(UPDATE_STATEMENT_TO_MIGRATE_POOL_AGENT_BINDING),
                     new_agent_id=new_id, old_agent_id=old_id)


def upgrade():
    conn = op.get_bind()
    rs = conn.execute(text(SQL_STATEMENT_TO_FIND_AGENTS), binary_type='f5-oslbaasv1-agent')
    result = rs.fetchall()
    for row in result:
        (id, device) = (row[0], row[1])
        print "migrating new agent %s for device %s" % (id, device)
        _migrate_agent_pool_binding(id, device, 'f5-bigip-lbaas-agent')


def downgrade():
    conn = op.get_bind()
    rs = conn.execute(text(SQL_STATEMENT_TO_FIND_AGENTS), binary_type='f5-bigip-lbaas-agent')
    result = rs.fetchall()
    for row in result:
        (id, device) = (row[0], row[1])
        print "rolling back agent %s for device %s" % (id, device)
        _migrate_agent_pool_binding(id, device,'f5-oslbaasv1-agent')


