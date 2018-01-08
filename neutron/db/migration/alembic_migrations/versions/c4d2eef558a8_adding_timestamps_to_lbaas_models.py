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

"""Adding timestamps to lbaas models

Revision ID: c4d2eef558a8
Revises: bd1bcb82f8a
Create Date: 2016-02-11 23:48:22.633779

"""

# revision identifiers, used by Alembic.
revision = 'c4d2eef558a8'
down_revision = 'bd1bcb82f8a'

from alembic import op
import sqlalchemy as sa
import datetime


def upgrade():
    op.add_column('sessionpersistences', sa.Column('created_at', sa.DateTime, default=datetime.datetime.now))
    op.add_column('sessionpersistences', sa.Column('updated_at', sa.DateTime, onupdate=datetime.datetime.now))
    op.add_column('poolstatisticss', sa.Column('created_at', sa.DateTime, default=datetime.datetime.now))
    op.add_column('poolstatisticss', sa.Column('updated_at', sa.DateTime, onupdate=datetime.datetime.now))
    op.add_column('vips', sa.Column('created_at', sa.DateTime, default=datetime.datetime.now))
    op.add_column('vips', sa.Column('updated_at', sa.DateTime, onupdate=datetime.datetime.now))
    op.add_column('members', sa.Column('created_at', sa.DateTime, default=datetime.datetime.now))
    op.add_column('members', sa.Column('updated_at', sa.DateTime, onupdate=datetime.datetime.now))
    op.add_column('pools', sa.Column('created_at', sa.DateTime, default=datetime.datetime.now))
    op.add_column('pools', sa.Column('updated_at', sa.DateTime, onupdate=datetime.datetime.now))
    op.add_column('pools', sa.Column('tenant_vpc', sa.String(255)))
    op.add_column('healthmonitors', sa.Column('created_at', sa.DateTime, default=datetime.datetime.now))
    op.add_column('healthmonitors', sa.Column('updated_at', sa.DateTime, onupdate=datetime.datetime.now))
    op.add_column('poolmonitorassociations', sa.Column('created_at', sa.DateTime, default=datetime.datetime.now))
    op.add_column('poolmonitorassociations', sa.Column('updated_at', sa.DateTime, onupdate=datetime.datetime.now))


def downgrade():
    op.drop_column('sessionpersistences', 'created_at')
    op.drop_column('sessionpersistences', 'updated_at')
    op.drop_column('poolstatisticss', 'created_at')
    op.drop_column('poolstatisticss', 'updated_at')
    op.drop_column('vips', 'created_at')
    op.drop_column('vips', 'updated_at')
    op.drop_column('members', 'created_at')
    op.drop_column('members', 'updated_at')
    op.drop_column('pools', 'created_at')
    op.drop_column('pools', 'updated_at')
    op.drop_column('pools', 'tenant_vpc')
    op.drop_column('healthmonitors', 'created_at')
    op.drop_column('healthmonitors', 'updated_at')
    op.drop_column('poolmonitorassociations', 'created_at')
    op.drop_column('poolmonitorassociations', 'updated_at')
