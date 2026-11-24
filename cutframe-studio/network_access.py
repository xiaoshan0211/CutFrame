"""按配置开放公司网段；不信任请求携带的代理地址。"""
import ipaddress


class NetworkAccess:
    def __init__(self, config):
        port = int(config.get('port', 4380))
        self.hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        self.network = None
        self.listen = '127.0.0.1'
        self.label = '仅本机'
        if config.get('lan_access'):
            address = ipaddress.IPv4Address(config['lan_address'])
            network = ipaddress.IPv4Network(config['lan_subnet'], strict=True)
            if not address.is_private or address.is_loopback or address not in network or network.prefixlen < 24:
                raise ValueError('局域网配置必须是明确的私有IPv4地址和不大于/24的网段')
            self.hosts.add(f'{address}:{port}')
            self.network = network
            self.listen = '0.0.0.0'
            self.label = '公司局域网'

    def check(self, host, remote, origin):
        if host not in self.hosts:
            return '访问地址未获授权'
        try:
            address = ipaddress.ip_address(remote or '')
        except ValueError:
            return '访问来源不可识别'
        if not address.is_loopback and not (self.network and address in self.network):
            return '仅允许本机和已配置的公司网段访问'
        if origin and origin != f'http://{host}':
            return '拒绝跨站请求'
        return None
