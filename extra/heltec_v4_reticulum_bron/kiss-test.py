import kiss

# Print function for incoming frames
def print_frame(frame):
    print(frame)

# Initialize serial KISS TNC on /dev/ttyUSB0 at 1200 baud
kiss_nc = kiss.SerialKISS('/dev/ttyACM0', 115200)
kiss_nc.start()

# Read data frames
kiss_nc.read(callback=print_frame)
