import bot
import keep_alive

# Start the web server in a separate thread
keep_alive.keep_alive()

# Run the bot main loop
bot.main()
