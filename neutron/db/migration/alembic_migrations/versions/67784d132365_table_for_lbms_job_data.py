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

"""table for lbms job data

Revision ID: 67784d132365
Revises: 470df2442b62
Create Date: 2016-11-14 16:59:57.954504

"""

# revision identifiers, used by Alembic.
revision = '67784d132365'
down_revision = '470df2442b62'

from alembic import op
import sqlalchemy as sa
import datetime



def upgrade():
    op.create_table(
        'lbmsdriver_job',
        sa.Column('id', sa.String(length=36), nullable=False, index=True),
        sa.Column('action', sa.String(length=255), nullable=False),
        sa.Column('data', sa.String(length=20480), nullable=False),
        sa.Column('created_at', sa.DateTime, default=datetime.datetime.now),
        sa.Column('updated_at', sa.DateTime, default=datetime.datetime.now)
    )

def downgrade():
    op.drop_table('lbmsdriver_job')
