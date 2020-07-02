import time
import xbmc
import xbmcaddon
import BaseHTTPServer
import httplib
import threading
from timeit import default_timer as timer

class MyRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/playback/time':
            if xbmc.Player().isPlaying():
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                
                player_time = xbmc.Player().getTime()
                self.wfile.write('%f' % (player_time))
                return
            else:
                self.send_response(404)
                return
        elif self.path == '/playback/status':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            if xbmc.Player().isPlaying():
                if is_playback_paused():
                    self.wfile.write('pause')
                else:
                    self.wfile.write('play')
            else:
                self.wfile.write('stop')
            return
        else:
            self.send_response(404)
            return
    def do_POST(self):
        self.handlePut()
    def do_PUT(self):
        self.handlePut()
    def handlePut(self):
        if self.path == '/playback/time':
            if xbmc.Player().isPlaying():
                content_len = int(self.headers.getheader('content-length', 0))
                put_body = self.rfile.read(content_len)
                new_time = float(put_body)
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                xbmc.Player().seekTime(new_time)
                player_time = xbmc.Player().getTime()
                # ensure that the call only returns when seeking is really finished (can only be guaranteed when playing)
                while (not is_playback_paused()) and (new_time >= xbmc.Player().getTime()) and (player_time > xbmc.Player().getTime()):
                    xbmc.sleep(5)
                player_time = xbmc.Player().getTime()
                self.wfile.write('%f' % (player_time))
                return
            else:
               self.send_response(404)
               return
        elif self.path == '/playback/status':
            content_len = int(self.headers.getheader('content-length', 0))
            put_body = self.rfile.read(content_len)
            if put_body == 'stop':
                xbmc.Player().stop()
                self.send_response(200)
            elif put_body == 'pause':
                xbmc.Player().pause()
                self.send_response(200)
            elif put_body == 'play':
                xbmc.Player().play()
                self.send_response(200)
            else:
                self.send_response(400)
            self.end_headers()
            return
        
        else:
            self.send_response(404)
            return

class StoppableHTTPServer(BaseHTTPServer.HTTPServer):
    def run(self):
        try:
            self.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            # Clean-up server (close socket, etc.)
            self.server_close()

def is_playback_paused():
    return bool(xbmc.getCondVisibility("Player.Paused"))

def is_player_seeking():
    return bool(xbmc.getCondVisibility("Player.Seeking"))

# retrieve the current player time as float in secs) from master rest api
def get_master_time(conn):
    url = '/playback/time'
    headers = {"Content-type": "text/plain", "Accept": "text/plain", "Cache-Control": "no-cache", "Pragma": "no-cache", "Expires": "0"}
    conn.request("GET", url, '', headers)
    r = conn.getresponse()
    if r.status == 200:
        master_time = float(r.read())
    else:
        master_time = -1
    return master_time

# moves the current player time (given as float secs) via master rest api
def seek_master_time(conn, new_master_time):
    url = '/playback/time'
    headers = {"Content-type": "text/plain", "Accept": "text/plain"}
    params = '%f' % (new_master_time)
    conn.request("PUT", url, params, headers)
    r = conn.getresponse()
    if r.status == 200:
        new_master_time = float(r.read())
    else:
        new_master_time = -1
    return new_master_time

# query master for its current playing status: {stop, play, pause} via rest api
def get_master_status(conn):
    url = '/playback/status'
    conn.request("GET", url)
    r = conn.getresponse()
    return r.read()

# sends "pause" signal to master via rest api
def pause_master(conn):
    url = '/playback/status'
    headers = {"Content-type": "text/plain", "Accept": "text/plain"}
    params = 'pause'
    conn.request("PUT", url, params, headers)
    r = conn.getresponse()
    return r.status

def check_resync(diff_ms_allowed, jump_ahead_time, manual_adjust_ms, master_ip, master_port):
    xbmc.log("Init resync check", level=xbmc.LOGNOTICE)
    if xbmc.Player().isPlaying():
        endpoint = master_ip + ':' + '%d' % (master_port)
        url = '/playback/time'
        # xbmc.log("Connecting to " + endpoint + url, level=xbmc.LOGNOTICE)
        conn = httplib.HTTPConnection(endpoint)
        curr_master_status = get_master_status(conn)
        self_paused = is_playback_paused()
        if curr_master_status == 'pause':
            if not self_paused:
                xbmc.Player().pause()
        else:
            if self_paused:
                xbmc.Player().pause()
        max_resync_loops = 10
        i = 0
        smallest_sleep_time_ms = 5
        start_get = timer()
        master_time = get_master_time(conn)
        end_get = timer()
        # if currently paused - only jump and that is all
        if curr_master_status == 'pause':
            xbmc.Player().seekTime(master_time)
            return
        own_time = xbmc.Player().getTime()
        master_own_time_diff = abs(own_time - master_time)
        dur_pause1 = 0.0
        cnt_pause1 = 0
        wait_for_pause1 = 0.05
        dur_getTime1 = 0.0
        cnt_getTime1 = 0
        wait_for_getTime1 = 0.05
        min_diff_time = 3.0 * 1.0 / 24 # at least 3 frames
        while (master_time >= 0) and (i < max_resync_loops) and (master_own_time_diff >= (diff_ms_allowed / 1000.0)):
            xbmc.log("sta %f master %f vs slave %f - %f >= %f?" % (i, own_time, master_time, master_own_time_diff, (diff_ms_allowed / 1000.0)), level=xbmc.LOGNOTICE)
            # resync
            new_own_time = master_time + jump_ahead_time
            xbmc.Player().seekTime(new_own_time)
            start_getTime = timer()
            master_time = get_master_time(conn)
            end_getTime = timer()
            dur_getTime1 += (end_getTime - start_getTime)
            cnt_getTime1 += 1
            wait_for_getTime1 = dur_getTime1 / cnt_getTime1
            own_time = xbmc.Player().getTime()
            round = 0
            max_pause_rounds = 1000
            start_pause1 = timer()
            if not is_playback_paused():
                xbmc.Player().pause()
            end_pause1 = timer()
            dur_pause1 += end_pause1 - start_pause1
            cnt_pause1 += 1
            wait_for_pause1 = dur_pause1 / cnt_pause1
            xbmc.log("mid1 %f own_time %f vs master_time %f - wait_for_pause1 %f" % (i, own_time, master_time, wait_for_pause1), level=xbmc.LOGNOTICE)
            # waiting by frequently checking against / updating master time
            while (round < max_pause_rounds) and (master_time >= 0) and ((own_time - ((smallest_sleep_time_ms / 1000.0) + wait_for_getTime1) * 2 - wait_for_pause1 - (manual_adjust_ms / 1000.0)) > master_time) and (own_time - master_time > min_diff_time):
                xbmc.sleep(smallest_sleep_time_ms)
                start_getTime = timer()
                master_time = get_master_time(conn)
                end_getTime = timer()
                dur_getTime1 += (end_getTime - start_getTime)
                cnt_getTime1 += 1
                wait_for_getTime1 = dur_getTime1 / cnt_getTime1
                round += 1
            # final little sleep, not re-checking master time anymore
            if (own_time - wait_for_pause1 - (manual_adjust_ms / 1000.0) - master_time) > 0:
                xbmc.sleep(int((own_time - wait_for_pause1 - (manual_adjust_ms / 1000.0) - master_time) * 1000))
            if is_playback_paused():
                xbmc.Player().pause()
            xbmc.log("mid2 %f own_time %f vs master_time %f - %f >= %f? - rounds %f - dur_pause1 %f - cnt_pause1 %f - wait_for_pause1 %f - dur_getTime1 %f - cnt_getTime1 %f - wait_for_getTime1 %f - final_wait %f" % (i, own_time, master_time, master_own_time_diff, (diff_ms_allowed / 1000.0), round, dur_pause1,cnt_pause1 , wait_for_pause1, dur_getTime1, cnt_getTime1, wait_for_getTime1, (own_time - wait_for_pause1 - master_time)), level=xbmc.LOGNOTICE)
            master_time = get_master_time(conn)
            own_time = xbmc.Player().getTime()
            master_own_time_diff = abs(own_time - master_time)
            xbmc.log("fin %f own_time %f vs master_time %f - %f >= %f? - rounds %f" % (i, own_time, master_time, master_own_time_diff, (diff_ms_allowed / 1000.0), round), level=xbmc.LOGNOTICE)
            # increase accuracy with the first rounds
            # if (i < 1) and (diff_ms_allowed >= 65.0):
            #    diff_ms_allowed = 65
            i += 1
        if master_time < 0:
            xbmc.log("Cannot connect to " + endpoint, level=xbmc.LOGNOTICE)
        conn.close()
    else:
        xbmc.log("Kodi is not playing", level=xbmc.LOGNOTICE)

if __name__ == '__main__':
    settings = xbmcaddon.Addon(id='service.sync.playback')
    own_port = int(settings.getSetting('own_port'))
    timeout = int(settings.getSetting('timeout'))
    master_slave = bool(settings.getSetting('master_slave'))
    diff_ms_allowed = int(settings.getSetting('diff_ms_allowed'))
    master_ip = settings.getSetting('master_ip')
    master_port = int(settings.getSetting('master_port'))
    jump_ahead_time = float(settings.getSetting('jump_ahead_time'))
    manual_adjust_ms = float(settings.getSetting('manual_adjust_ms'))
    xbmc.log('Starts play-sync the REST server at own_port %d' % own_port,level=xbmc.LOGNOTICE)
    http_server = StoppableHTTPServer(('', own_port), MyRequestHandler)
    thread = threading.Thread(None, http_server.run)
    thread.start()
    xbmc.log('REST server at own_port %d started' % own_port,level=xbmc.LOGNOTICE)

    monitor = xbmc.Monitor()
    
    while not monitor.abortRequested():
        if master_slave:
            check_resync(diff_ms_allowed, jump_ahead_time, manual_adjust_ms, master_ip, master_port)
        # Sleep/wait for abort for <timeout> seconds
        if monitor.waitForAbort(timeout):
            # Abort was requested while waiting. We should exit
            break
    http_server.shutdown()
    thread.join()

