"""Account login against RPCN, carried as a stateless bearer token.

Other modules take the signed-in user through `auth.dependencies.current_user`
and never look at the token themselves.
"""
