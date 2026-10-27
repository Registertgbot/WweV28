from handlers import access, admin, broadcast, collect, moderation, season, fighter, help, history, leaderboard, match, moves, hub, mitb, mycard, profile, shop, titles, rumble, start, tag, tour

routers = [access.router, moderation.router, season.router, broadcast.router, collect.router, fighter.router, mycard.router, shop.router, titles.router, start.router, help.router, match.router, moves.router, profile.router,
           leaderboard.router, history.router, rumble.router, tag.router, mitb.router, tour.router, hub.router, admin.router]
