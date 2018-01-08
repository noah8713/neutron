import neutron.services.loadbalancer.agent_scheduler as base_scheduler
import neutron.db.agents_db as agents_db
import lbms_client as lbms_client_api
from oslo_config import cfg
from neutron.openstack.common import loopingcall
from neutron.openstack.common import log as logging
import neutron.services.loadbalancer.drivers.lbms.lbms_client as lbms
from neutron.db import api as db
import json
from neutron import context as n_ctx



LBMS_AGENT_BINARY = 'lbms-lbaas-agent'
LOG = logging.getLogger(__name__)

__author__ = 'kugandhi'

class LbmsSchedulerAgentDbMixin(agents_db.AgentDbMixin):

    def __init__(self, plugin):
        LOG.info('initializing the LbmsSchedulerAgentDbMixin')
        self.plugin = plugin
        self.lbms_client = lbms.LbmsClient()

    def update_agent_data(self, agent):
        LOG.info('starting to update the agent %s' % agent.host)
        lb_name = agent.host

        # call LBMS API to check the lb (host) health.
        response = self.lbms_client.get_lbms_health()
        LOG.info('response from lb %s' % response)

        # update the agent table with the health information
        if response:
            LOG.info('updating the agent record')
            agent['configurations'] = json.loads(agent['configurations'])
            self.plugin.create_or_update_agent(n_ctx.get_admin_context(), agent)
        else:
            LOG.error('An error in getting response from LBMS for lb [%s], error message [%s]'
                      % (lb_name, response))

    def report_state(self):

        try:
            agents_list = self.plugin.get_agents_db(n_ctx.get_admin_context(), filters={
                    'binary': [LBMS_AGENT_BINARY],
                    'admin_state_up': [True]})

            LOG.info('agent list %s' % agents_list)
            for agent in agents_list:
                self.update_agent_data(agent)
        except Exception, e:
            LOG.error('unable to update the lbms agent state %s' % e)


class LbmsScheduler(base_scheduler.ChanceScheduler):

    def __init__(self, plugin):

        LOG.info('starting the lbms scheduler')
        # periodic tasks to monitor the load balancers registered as agents.
        report_interval = cfg.CONF.lbms_driver.report_interval
        if report_interval:
            agent_scheduler = LbmsSchedulerAgentDbMixin(plugin)
            heartbeat = loopingcall.FixedIntervalLoopingCall(agent_scheduler.report_state)
            heartbeat.start(interval=report_interval)


    # In the first version, schedule is going to be a simple one.
    # Just get the first lbms agent from the agent list
    def schedule(self, plugin, context, pool):

        agents_list = plugin.get_agents_db(context, filters={
            'binary': [LBMS_AGENT_BINARY],
            'admin_state_up': [True]})

        candidates_list = [x for x in agents_list if x.is_active
                           and 'subnets' in x['configurations']
                           and pool['subnet_id'] in json.loads(x['configurations'])['subnets']]



        if len(candidates_list) > 0:
            # Create the agent pool binding
            binding = base_scheduler.PoolLoadbalancerAgentBinding()
            binding.agent = candidates_list[0]
            binding.pool_id = pool['id']
            context.session.add(binding)
            LOG.info('selecting the agent with host %s' % candidates_list[0].host)

            return candidates_list[0]



