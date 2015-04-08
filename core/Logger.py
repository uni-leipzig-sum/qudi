import time
import traceback
import sys, os

from pyqtgraph.debug import *
import pyqtgraph.debug as pgdebug
import pyqtgraph.configfile as configfile
from pyqtgraph.Qt import QtCore
from .util.Mutex import Mutex
import numpy as np
import weakref
import re

## install global exception handler for others to hook into.
import pyqtgraph.exceptionHandling as exceptionHandling
exceptionHandling.setTracebackClearing(True)

global LOG
LOG = None

global blockLogging
blockLogging = False

global original_excepthook
original_excepthook = sys.excepthook

def printExc(msg='', indent=4, prefix='|', msgType='error'):
    """Print an error message followed by an indented exception backtrace
    (This function is intended to be called within except: blocks)"""
    pgdebug.printExc(msg, indent, prefix)

class Logger(QtCore.QObject):

    def __init__(self, manager):
        super().__init__()
        path = os.path.dirname(__file__)
        self.manager = manager
        self.msgCount = 0
        self.logCount=0
        self.logFile = None
        ## start a new temp log file, destroying anything left over
        ## from the last session.
        configfile.writeConfigFile('', self.fileName())  
        self.lock = Mutex()
        exceptionHandling.register(self.exceptionCallback)

    def exceptionCallback(self,*args):
        ## Called whenever there is an unhandled exception.
    
        ## unhandled exceptions generate an error message by default, but this
        ## can be overridden
        global blockLogging
        ## if an error occurs *while* trying to log another exception,
        ## disable any further logging to prevent recursion.
        if not blockLogging:
            try:
                blockLogging = True
                self.logMsg("Unexpected error: ",
                            exception=args,
                            msgType='error')
                ex_type, ex_value, ex_traceback = args
                print(ex_type)
                if ex_type == KeyboardInterrupt:
                    self.manager.quit()
            except:
                print("Error: Exception could no be logged.")
                original_excepthook(*sys.exc_info())
            finally:
                blockLogging = False

    ## called indirectly when logMsg is called from a non-gui thread 
    def queuedLogMsg(self, args):
        self.logMsg(*args[0], **args[1])
        
    def print_logMsg(self, msg, **kwargs):
        print(msg)
        self.logMsg(msg, **kwargs)

    def logMsg(self, msg, importance=5, msgType='status', **kwargs):
        """msg: the text of the log message
           msgTypes: user, status, error, warning (status is default)
           importance: 0-9 (0 is low importance, 9 is high, 5 is default)
           other keywords:
              exception: a tuple (type, exception, traceback) as returned by
              sys.exc_info()
              docs: a list of strings where documentation related to the message
              can be found
              reasons: a list of reasons (as strings) for the message
              traceback: a list of formatted callstack/trackback objects
              (formatting a traceback/callstack returns a list of strings),
              usually looks like
              [['line 1', 'line 2', 'line3'], ['line1', 'line2']]
           Feel free to add your own keyword arguments.
           These will be saved in the log.txt file,
           but will not affect the content or way that messages are displayed.
        """
        currentDir = None
        
        now = str(time.strftime('%Y.%m.%d %H:%M:%S'))
        name = 'LogEntry_' + str(self.msgCount)
        self.msgCount += 1
        entry = {
            #'docs': None,
            #'reasons': None,
            'message': msg,
            'timestamp': now,
            'importance': importance,
            'msgType': msgType,
            #'exception': exception,
            'id': self.msgCount,
        }
        for k in kwargs:
            entry[k] = kwargs[k]
            
        self.processEntry(entry)
        
        ## Allow exception to override values in the entry
        if entry.get('exception', None) is not None and 'msgType' in entry['exception']:
            entry['msgType'] = entry['exception']['msgType']
        
        self.saveEntry({name:entry})
        
        if entry['msgType'] == 'error':
            #FIXME:  there should be some sort of visible alert
            pass
        
    def logExc(self, *args, **kwargs):
        """Calls logMsg, but adds in the current exception and callstack.
        Must be called within an except block, and should only be called if the
        exception is not re-raised.
        Unhandled exceptions, or exceptions that reach the top of the callstack
        are automatically logged, so logging an exception that will be re-raised
        can cause the exception to be logged twice.
        Takes the same arguments as logMsg."""
        kwargs['exception'] = sys.exc_info()
        kwargs['traceback'] = traceback.format_stack()[:-2] + ["------- exception caught ---------->\n"]
        self.logMsg(*args, **kwargs)
        
    def processEntry(self, entry):
        ## pre-processing common to saveEntry and displayEntry

        ## convert exc_info to serializable dictionary
        if entry.get('exception', None) is not None:
            exc_info = entry.pop('exception')
            entry['exception'] = self.exceptionToDict(*exc_info, 
                                        topTraceback=entry.get('traceback', []))
        else:
            entry['exception'] = None

    def exceptionToDict(self, exType, exc, tb, topTraceback):
        #lines = (traceback.format_stack()[:-skip] 
            #+ ["  ---- exception caught ---->\n"] 
            #+ traceback.format_tb(sys.exc_info()[2])
            #+ traceback.format_exception_only(*sys.exc_info()[:2]))
        #print topTraceback
        excDict = {}
        excDict['message'] = traceback.format_exception(exType, exc, tb)[-1][:-1] 
        excDict['traceback'] = topTraceback + traceback.format_exception(exType, exc, tb)[:-1]
        if hasattr(exc, 'docs'):
            if len(exc.docs) > 0:
                excDict['docs'] = exc.docs
        if hasattr(exc, 'reasons'):
            if len(exc.reasons) > 0:
                excDict['reasons'] = exc.reasons
        if hasattr(exc, 'kwargs'):
            for k in exc.kwargs:
                excDict[k] = exc.kwargs[k]
        if hasattr(exc, 'oldExc'):
            excDict['oldExc'] = self.exceptionToDict(*exc.oldExc, topTraceback=[])
        return excDict
    
    def fileName(self):
        ## return the log file currently used
        if self.logFile is None:
            return "tempLog.txt"
        else:
            return self.logFile.name()

    def getLogDir(self):
        return None
    
    def saveEntry(self, entry):
        with self.lock:
            configfile.appendConfigFile(entry, self.fileName())
