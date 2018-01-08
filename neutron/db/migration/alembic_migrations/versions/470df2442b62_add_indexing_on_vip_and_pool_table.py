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

"""add indexing on vip and pool table

Revision ID: 470df2442b62
Revises: c4d2eef558a8
Create Date: 2016-11-14 15:58:39.924935

"""

# revision identifiers, used by Alembic.
revision = '470df2442b62'
down_revision = 'c4d2eef558a8'

from alembic import op
import sqlalchemy as sa

from neutron.db import migration


VIP_TENANT_INDEX_NAME = 'viptenantidindex'
VIP_NAME_INDEX_NAME = 'vipnameindex'
POOL_TENANT_INDEX_NAME = 'pooltenantidindex'
POOL_NAME_INDEX_NAME = 'poolnameindex'

VIP_TABLE_NAME = 'vip'
POOL_TABLE_NAME = 'pool'

def upgrade():
    if migration.schema_has_table(VIP_TABLE_NAME):
        op.create_index(
            index_name=VIP_TENANT_INDEX_NAME,
            table_name=VIP_TABLE_NAME,
            columns=['tenant_id']
        )
        op.create_index(
            index_name=VIP_NAME_INDEX_NAME,
            table_name=VIP_TABLE_NAME,
            columns=['name']
        )

    if migration.schema_has_table(POOL_TABLE_NAME):
        op.create_index(
            index_name=POOL_TENANT_INDEX_NAME,
            table_name=POOL_TABLE_NAME,
            columns=['tenant_id']
        )
        op.create_index(
            index_name=POOL_NAME_INDEX_NAME,
            table_name=POOL_TABLE_NAME,
            columns=['name']
        )


def downgrade():
    pass
