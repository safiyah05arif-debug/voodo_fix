import socket,ssl,certifi
host='159.41.188.47'
try:
    s=socket.create_connection((host,27017),5)
    ctx=ssl.create_default_context(cafile=certifi.where())
    ss=ctx.wrap_socket(s,server_hostname='cluster0.ujb8c5b.mongodb.net')
    print('TLS ok', ss.version())
    print('cert subject', ss.getpeercert().get('subject'))
    ss.close()
except Exception as e:
    print('ERROR', repr(e))
